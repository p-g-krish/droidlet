import ast
import json
import copy
from pprint import pprint
import os
import argparse

# Construct maps of tools A->D
toolC_map = {}
toolD_map = {}
toolA_map = {}
toolB_map = {}
toolC_updated_map = {}


def collect_tool_outputs(tool_C_out_file, tool_D_out_file):
    # check if all keys of tool C annotated yes -> put directly
    # if no , check child in t2 and combine
    if os.path.exists(tool_C_out_file):
        with open(tool_C_out_file) as f:
            for line in f.readlines():
                line = line.strip()
                cmd, ref_obj_text, a_d = line.split("\t")
                if cmd in toolC_map:
                    toolC_map[cmd].update(ast.literal_eval(a_d))
                else:
                    toolC_map[cmd] = ast.literal_eval(a_d)
    # print("toolC map keys")
    # print(toolC_map.keys())

    if os.path.exists(tool_D_out_file):
        with open(tool_D_out_file) as f2:
            for line in f2.readlines():
                line = line.strip()
                cmd, comparison_text, comparison_dict = line.split("\t")
                if cmd in toolD_map:
                    print("Error: command {} is in the tool D outputs".format(cmd))
                # add the comparison dict to command -> dict
                toolD_map[cmd] = ast.literal_eval(comparison_dict)
    # print("toolD map keys")
    # print(toolD_map.keys())


def all_yes(a_dict):
    if type(a_dict) == str:
        a_dict = ast.literal_eval(a_dict)
    for k, val in a_dict.items():
        if type(val) == list and val[0] == "no":
            return False
    return True


def clean_up_dict(a_dict):
    if type(a_dict) == str:
        a_dict = ast.literal_eval(a_dict)
    new_d = {}
    for k, val in a_dict.items():
        if type(val) == list:
            if val[0] in ["yes", "no"]:
                new_d[k] = val[1]
        elif type(val) == dict:
            new_d[k] = clean_up_dict(val)
        else:
            new_d[k] = val
    return new_d


# post_process spans and "contains_coreference" : "no"
def merge_indices(indices):
    a, b = indices[0]
    for i in range(1, len(indices)):
        a = min(a, indices[i][0])
        b = max(b, indices[i][1])
    return [a, b]


def fix_spans(d):
    new_d = {}
    if type(d) == str:
        d = ast.literal_eval(d)
    for k, v in d.items():
        if k == "contains_coreference" and v == "no":
            continue
        if type(v) == list:
            new_d[k] = [0, merge_indices(v)]
            continue
        elif type(v) == dict:
            new_d[k] = fix_spans(v)
            continue
        else:
            new_d[k] = v
    return new_d


def fix_ref_obj(clean_dict):
    val = clean_dict
    new_clean_dict = {}
    if "special_reference" in val:
        new_clean_dict["special_reference"] = val["special_reference"]
        val.pop("special_reference")
    # NOTE: this needs to be changed
    if "repeat" in val:
        new_clean_dict["repeat"] = val["repeat"]
        val.pop("repeat")
    if val:
        # Add selectors to filters if there is a location
        if "location" in val:
            val["selector"] = {
                    "location": val["location"]
            }
            del val["location"]
        # Put has_x attributes in triples
        # Put triples inside "where_clause"
        triples = []
        for k, v in [x for x in val.items()]:
            if "has_" in k:
                triples.append({
                    "pred_text": k,
                    "obj_text": v
                })
                del val[k]
        if len(triples) > 0:
            if "where_clause" not in val:
                val["where_clause"] = {"AND": []}
            val["where_clause"]["AND"] =  triples
            # val["triples"] = triples
        new_clean_dict["filters"] = val
    return new_clean_dict


def combine_tool_cd_make_ab(tool_A_out_file, tool_B_out_file):
    # combine and write output to a file
    # what these action will look like in the map
    i = 0
    # update dict of toolC with tool D and keep that in tool C's map
    for cmd, a_dict in toolC_map.items():
        # remove the ['yes', val] etc
        for key in a_dict.keys():
            a_dict_child = a_dict[key]
            clean_dict = clean_up_dict(a_dict_child)
            # fix reference object inside location of reference object
            if "location" in clean_dict and "reference_object" in clean_dict["location"]:
                value = clean_dict["location"]["reference_object"]
                clean_dict["location"]["reference_object"] = fix_ref_obj(value)
            new_clean_dict = fix_ref_obj(clean_dict)

            if all_yes(a_dict_child):
                if cmd in toolC_updated_map:
                    toolC_updated_map[cmd][key] = new_clean_dict
                else:
                    toolC_updated_map[cmd] = {key: new_clean_dict}
                continue
            new_clean_dict.pop("comparison", None)
            comparison_dict = toolD_map[cmd]  # check on this again

            valid_dict = {}
            valid_dict[key] = {}
            valid_dict[key]["filters"] = new_clean_dict
            valid_dict[key]["filters"].update(comparison_dict)
            toolC_updated_map[cmd] = valid_dict  # only gets populated if filters exist
    # print("in combine_tool_cd_make_ab...")
    # pprint(toolC_updated_map)

    # combine outputs
    # check if all keys of t1 annotated yes -> put directly
    # if no , check child in t2 and combine
    # construct mape of tool 1
    with open(tool_A_out_file) as f:
        for line in f.readlines():
            line = line.strip()
            cmd, a_d = line.split("\t")
            cmd = cmd.strip()
            toolA_map[cmd] = a_d
    # pprint(toolA_map)

    # construct map of tool 2

    if os.path.isfile(tool_B_out_file):
        with open(tool_B_out_file) as f2:
            for line in f2.readlines():
                line = line.strip()
                cmd, child, child_dict = line.split("\t")
                cmd = cmd.strip()
                child = child.strip()
                if cmd in toolB_map and child in toolB_map[cmd]:
                    print("BUGGG")
                if cmd not in toolB_map:
                    toolB_map[cmd] = {}
                toolB_map[cmd][child] = child_dict
    # pprint(toolB_map)


def all_yes(a_dict):
    if type(a_dict) == str:
        a_dict = ast.literal_eval(a_dict)
    for k, val in a_dict.items():
        if type(val) == list and val[0] == "no":
            return False
    return True


def clean_dict_1(a_dict):
    if type(a_dict) == str:
        a_dict = ast.literal_eval(a_dict)
    new_d = {}
    for k, val in a_dict.items():
        if type(val) == list:
            if val[0] in ["yes", "no"]:
                new_d[k] = val[1]
        elif type(val) == dict:
            new_d[k] = a_dict(val[1])
        else:
            new_d[k] = val
    # only for now
    if "dance_type_span" in new_d:
        new_d["dance_type"] = {}
        new_d["dance_type"]["dance_type_name"] = new_d["dance_type_span"]
        new_d.pop("dance_type_span")
    if "dance_type_name" in new_d:
        new_d["dance_type"] = {}
        new_d["dance_type"]["dance_type_name"] = new_d["dance_type_name"]
        new_d.pop("dance_type_name")
    return new_d


# post_process spans and "contains_coreference" : "no"
def merge_indices(indices):
    a, b = indices[0]
    for i in range(1, len(indices)):
        a = min(a, indices[i][0])
        b = max(b, indices[i][1])
    return [a, b]


def fix_put_mem(d):

    if type(d) == str:
        d = ast.literal_eval(d)
    new_d = copy.deepcopy(d)
    del new_d["action_type"]
    if "has_tag" in new_d and "upsert" in new_d:
        new_d["upsert"]["memory_data"]["has_tag"] = new_d["has_tag"]
        del new_d["has_tag"]

    return new_d


def fix_spans(d):
    new_d = {}
    if type(d) == str:
        d = ast.literal_eval(d)
    for k, v in d.items():
        if k == "contains_coreference" and v == "no":
            continue
        if type(v) == list:
            if k != "triples":
                if k == "tag_val":
                    new_d["has_tag"] = [0, merge_indices(v)]
                else:
                    new_d[k] = [0, merge_indices(v)]
            else:
                new_d[k] = [fix_spans(x) for x in v]
                continue
        elif type(v) == dict:
            new_d[k] = fix_spans(v)
            continue
        else:
            new_d[k] = v
    return new_d


def update_action_dictionaries(all_combined_path):
    # combine and write output to a file
    i = 0
    # what these action will look like in the map
    dance_type_map = {"point": "point",
                      "look": "look_turn",
                      "turn": "body_turn"}

    # update dict of tool1 with tool 2
    with open(all_combined_path, "w") as f:
        for cmd, a_dict in toolA_map.items():
            # remove the ['yes', val] etc
            clean_dict = clean_dict_1(a_dict)
            if all_yes(a_dict):
                action_type = clean_dict["action_type"]
                valid_dict = {}
                valid_dict["dialogue_type"] = clean_dict["dialogue_type"]
                del clean_dict["dialogue_type"]
                clean_dict["action_type"] = clean_dict["action_type"].upper()
                act_dict = fix_spans(clean_dict)
                valid_dict["action_sequence"] = [act_dict]

                f.write(cmd + "\t" + json.dumps(valid_dict) + "\n")
                print(cmd)
                print(valid_dict)
                print("All yes")
                print("*" * 20)
                continue
            if clean_dict["action_type"] == "noop":
                f.write(cmd + "\t" + json.dumps(clean_dict) + "\n")
                print(clean_dict)
                print("NOOP")
                print("*" * 20)
                continue
            if clean_dict["action_type"] == "otheraction":
                f.write(cmd + "\t" + str(a_dict) + "\n")
                continue

            if toolB_map and cmd in toolB_map:
                child_dict_all = toolB_map[cmd]
                # update action dict with all children except for reference object
                for k, v in child_dict_all.items():
                    if k not in clean_dict:
                        print("BUGGGG")
                    if type(v) == str:
                        v = ast.literal_eval(v)
                    if not v:
                        continue

                    if "reference_object" in v[k]:
                        value = v[k]["reference_object"]
                        v[k]["reference_object"] = fix_ref_obj(value)
                    if k == "tag_val":
                        clean_dict.update(v)
                    elif k == "facing":
                        action_type = clean_dict["action_type"]
                        # set to dance
                        clean_dict["action_type"] = "DANCE"
                        clean_dict["dance_type"] = {dance_type_map[action_type]: v["facing"]}
                        clean_dict.pop("facing")
                    else:
                        clean_dict[k] = v[k]
            ref_obj_dict = {}
            if toolC_updated_map and cmd in toolC_updated_map:
                ref_obj_dict = toolC_updated_map[cmd]
            clean_dict.update(ref_obj_dict)
            if "receiver_reference_object" in clean_dict:
                clean_dict["receiver"] = {"reference_object": clean_dict["receiver_reference_object"]}
                clean_dict.pop("receiver_reference_object")
            if "receiver_location" in clean_dict:
                clean_dict["receiver"] = {"location": clean_dict["receiver_location"]}
                clean_dict.pop("receiver_location")

            actual_dict = copy.deepcopy((clean_dict))

            action_type = actual_dict["action_type"]

            valid_dict = {}
            valid_dict["dialogue_type"] = actual_dict["dialogue_type"]
            del actual_dict["dialogue_type"]
            actual_dict["action_type"] = actual_dict["action_type"].upper()
            act_dict = fix_spans(actual_dict)
            valid_dict["action_sequence"] = [act_dict]
            print(cmd)
            pprint(valid_dict)
            print("*" * 40)
            f.write(cmd + "\t" + json.dumps(valid_dict) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    # Default to directory of script being run for writing inputs and outputs
    default_write_dir = os.path.dirname(os.path.abspath(__file__))
    
    parser.add_argument("--write_dir_path", type=str, default=default_write_dir)
    args = parser.parse_args()

    # This must exist since we are using tool A outputs
    folder_name_A = '{}/A/all_agreements.txt'.format(args.write_dir_path)
    folder_name_B = '{}/B/all_agreements.txt'.format(args.write_dir_path)
    folder_name_C = '{}/C/all_agreements.txt'.format(args.write_dir_path)
    folder_name_D = '{}/D/all_agreements.txt'.format(args.write_dir_path)
    all_combined_path = '{}/all_combined.txt'.format(args.write_dir_path)

    collect_tool_outputs(folder_name_C, folder_name_D)
    combine_tool_cd_make_ab(folder_name_A, folder_name_B)
    update_action_dictionaries(all_combined_path)
