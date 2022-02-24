import a0
import signal
import requests

# read in the parameters from fsetup cfg
EVENT_NAME = a0.cfg(a0.env.topic(), "/ifttt/event_name", str)
KEY = a0.cfg(a0.env.topic(), "/ifttt/key", str)
EVENT_TOPIC = a0.cfg(a0.env.topic(), "/event_topic", str)
a0.update_configs()


def call_robo_crit_event(topic_name, pkt):
    print(f"Pinging IFTTT Event {EVENT_NAME}")

    # create a json object to hold the message data and other relevant info
    msg_data = {"Topic": topic_name, "msg": pkt.payload}
    resp = requests.post(
        f"https://maker.ifttt.com/trigger/{EVENT_NAME}/json/with/key/{KEY}",
        data=msg_data,
    )
    # note /json/with/key: json is reqd to read data being sent
    # skip the "/json" if only triggering is needed without any msgs

    print(resp.text)
    # "Congratulations! You've fired TRIGGER_EVENT_NAME event"


s = a0.Subscriber(
    f"{EVENT_TOPIC}",
    lambda pkt: call_robo_crit_event(f"{EVENT_TOPIC}", pkt),
)

signal.pause()
