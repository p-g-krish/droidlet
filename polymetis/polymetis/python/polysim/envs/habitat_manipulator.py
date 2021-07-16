import os
import numpy as np
import torch

from omegaconf import DictConfig
import habitat_sim
import magnum as mn

import cv2

from polysim.envs import AbstractControlledEnv
from polymetis.utils.data_dir import get_full_path_to_urdf

import torchcontrol as toco


def make_configuration(habitat_dir):
    # simulator configuration
    backend_cfg = habitat_sim.SimulatorConfiguration()
    backend_cfg.scene_id = os.path.join(
        habitat_dir, "data", "scene_datasets/habitat-test-scenes/apartment_1.glb"
    )
    backend_cfg.enable_physics = True
    backend_cfg.physics_config_file = os.path.join(
        habitat_dir, backend_cfg.physics_config_file
    )

    # sensor configurations
    # Note: all sensors must have the same resolution
    # setup 2 rgb sensors for 1st and 3rd person views
    camera_resolution = [540, 720]
    sensors = {
        "rgba_camera_1stperson": {
            "sensor_type": habitat_sim.SensorType.COLOR,
            "resolution": camera_resolution,
            "position": [0.0, 0.0, 0.0],
            "orientation": [0.0, 0.0, 0.0],
        },
        "depth_camera_1stperson": {
            "sensor_type": habitat_sim.SensorType.DEPTH,
            "resolution": camera_resolution,
            "position": [0.0, 0.0, 0.0],
            "orientation": [0.0, 0.0, 0.0],
        },
    }

    sensor_specs = []
    for sensor_uuid, sensor_params in sensors.items():
        sensor_spec = habitat_sim.CameraSensorSpec()
        sensor_spec.uuid = sensor_uuid
        sensor_spec.sensor_type = sensor_params["sensor_type"]
        sensor_spec.resolution = sensor_params["resolution"]
        sensor_spec.position = sensor_params["position"]
        sensor_spec.orientation = sensor_params["orientation"]
        sensor_specs.append(sensor_spec)

    # agent configuration
    agent_cfg = habitat_sim.agent.AgentConfiguration()
    agent_cfg.sensor_specifications = sensor_specs

    return habitat_sim.Configuration(backend_cfg, [agent_cfg])


def place_agent(sim):
    # place our agent in the scene
    agent_state = habitat_sim.AgentState()
    agent_state.position = [-0.15, -0.1, 1.0]
    # agent_state.position = [-0.15, -1.6, 1.0]
    agent_state.rotation = np.quaternion(-0.83147, 0, 0.55557, 0)
    agent = sim.initialize_agent(0, agent_state)
    return agent.scene_node.transformation_matrix()


def place_robot_from_agent(
    sim,
    robot_id,
    angle_correction=-1.56,
    local_base_pos=None,
):
    if local_base_pos is None:
        local_base_pos = np.array([0.0, -1.1, -2.0])
    # place the robot root state relative to the agent
    agent_transform = sim.agents[0].scene_node.transformation_matrix()
    base_transform = mn.Matrix4.rotation(
        mn.Rad(angle_correction), mn.Vector3(1.0, 0, 0)
    )
    base_transform.translation = agent_transform.transform_point(local_base_pos)
    sim.set_articulated_object_root_state(robot_id, base_transform)


class HabitatManipulatorEnv(AbstractControlledEnv):
    def __init__(
        self,
        robot_model_cfg: DictConfig,
        hz: int,
        habitat_dir: str,
        gui=False,
        joint_damping=0.1,
        grav_comp=True,
    ):
        self.hz = hz
        self.dt = 1.0 / self.hz
        self.gui = gui
        self.n_dofs = robot_model_cfg.num_dofs
        self.grav_comp = grav_comp

        self.robot_model_cfg = robot_model_cfg
        self.robot_description_path = get_full_path_to_urdf(
            self.robot_model_cfg.robot_description_path
        )

        self.robot_model = toco.models.RobotModelPinocchio(
            self.robot_description_path, self.robot_model_cfg.ee_joint_name
        )

        self.habitat_cfg = make_configuration(habitat_dir)
        self.sim = habitat_sim.Simulator(self.habitat_cfg)
        place_agent(self.sim)

        self.robot_id = self.sim.add_articulated_object_from_urdf(
            self.robot_description_path, True
        )

        self.sim.set_articulated_object_motion_type(
            self.robot_id, habitat_sim.physics.MotionType.DYNAMIC
        )
        assert (
            self.sim.get_articulated_object_motion_type(self.robot_id)
            == habitat_sim.physics.MotionType.DYNAMIC
        )

        for motor_id in range(self.n_dofs):
            joint_motor_settings = habitat_sim.physics.JointMotorSettings(
                0.0,  # position_target
                0.0,  # position_gain
                0.0,  # velocity_target
                joint_damping,  # velocity_gain
                0.0,  # max_impulse
            )
            self.sim.update_joint_motor(self.robot_id, motor_id, joint_motor_settings)
            self.sim.set_articulated_link_friction(self.robot_id, motor_id, 0.0)

        self.reset()

    def reset(self):
        self.sim.reset_articulated_object(self.robot_id)
        place_robot_from_agent(self.sim, self.robot_id)

    def get_num_dofs(self):
        return self.n_dofs

    def get_current_joint_pos_vel(self):
        pos = self.sim.get_articulated_object_positions(self.robot_id)
        vel = self.sim.get_articulated_object_velocities(self.robot_id)
        return pos, vel

    def get_current_joint_torques(self):
        tau = self.sim.get_articulated_object_forces(self.robot_id)
        return (tau, tau, tau, tau)

    def grav_comp(self, pos, vel):
        return (
            self.robot_model.inverse_dynamics(
                torch.tensor(pos),
                torch.tensor(vel),
                torch.tensor([0 for _ in range(self.n_dofs)]),
            )
            .detach()
            .cpu()
            .numpy()
        )

    def apply_joint_torques(self, torques):
        pos, vel = self.get_current_joint_pos_vel()

        grav_comp_torques = self.grav_comp(pos, vel)
        if self.grav_comp:
            applied_torques = (np.array(torques) + grav_comp_torques).tolist()
        else:
            applied_torques = torques

        curr_torques = self.sim.get_articulated_object_forces(
            self.robot_id
        )  # should always be 0 at this point
        if curr_torques != [0, 0, 0, 0, 0, 0, 0]:
            # Extremely important; otherwise occasionally the simulation will
            # put the articulated object to sleep (maybe limit violations?)
            assert self.sim.get_articulated_object_sleep(self.robot_id)
            self.sim.set_articulated_object_sleep(self.robot_id, False)

        self.sim.set_articulated_object_forces(self.robot_id, applied_torques)
        self.sim.step_physics(self.dt)

        if self.gui:
            obs = self.sim.get_sensor_observations()

            cv2.namedWindow("Habitat", cv2.WINDOW_AUTOSIZE)
            cv2.imshow("Habitat", obs["rgba_camera_1stperson"])
            key = cv2.waitKey(1)

        return torques
