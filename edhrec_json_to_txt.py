import json
import os
from tkinter import filedialog, Tk
import requests
import re
import random
import math

def format_commander_name(commander_name:str):
    non_alphas_regex = r"[^\w\s]" # Everything that's not alphanumeric or space
    formatted_name = re.sub(non_alphas_regex, "", commander_name)
    formatted_name = formatted_name.lower() # Make lowercase
    formatted_name = formatted_name.replace(" ", "-")  # Replace spaces with hyphens
    print(f"In format_commander_name and formatted name is {formatted_name}")
    return formatted_name

def request_json(commander_name:str):
    formatted_name = format_commander_name(commander_name)
    json_url = f"https://json.edhrec.com/pages/commanders/{formatted_name}.json"
    response = requests.get(json_url)
    if response.status_code == 200:
        json_data = response.json()
        print(f"JSON request successful!")
        return json_data
    else:
        print(f"JSON request failed! Try different commander name")

def browse_json_filepath():
    json_file_path = filedialog.askopenfilename(title="Select the EDHREC JSON file", filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
    if json_file_path:
        print(f"Selected file {json_file_path}")
        return json_file_path
    else:
        print(f"Canceled")
        return 
    
def browse_output_directory(title:str):
    output_directory = filedialog.askdirectory(title=title)
    if not (output_directory):
        print(f"Canceled")
        return
    return output_directory
    
def read_json_file(json_file_path:str):
    try:
        with open (json_file_path, "r") as json_file:
            json_data = json.load(json_file)
            return json_data
    except Exception as e:
        print(f"Error reading JSON file: {e}")

def save_list_of_dicts(list_of_dicts:list[dict], output_path:str, output_filename:str):
    full_output_path = os.path.join(output_path, output_filename)
    with open (full_output_path, "w") as output_file:
        for dict in list_of_dicts:
            for key, value in dict.items():
                output_file.write(f"{key}: {value}\n")
                print(f"{key} written to file {output_filename}")

def save_dict_of_lists(dict_of_lists:dict[list], output_path:str):
    for dict_key, dict_val in dict_of_lists.items():
        # output_filepath = f"{output_path}/{dict_key}.txt"
        output_filepath = os.path.join(output_path, dict_key + ".txt")
        with open(output_filepath, "w", newline="") as file:
            for list_item in dict_val:
                file.write(f"{list_item}\n")
            print(f"{dict_key} saved to file {output_filepath}")

def save_info(dict_of_dicts:dict[dict], output_path:str):
    for dict_key, dict_val in dict_of_dicts.items():
        output_filepath = os.path.join(output_path, "Info.txt")
        # output_filepath = f"{output_path}/{dict_key}.txt"
        with open(output_filepath, "w", newline="") as file:
            file.write(f"{dict_key}:\n")
            for inner_dict_key, inner_dict_val in dict_val.items():
                file.write(f"{inner_dict_key}: {inner_dict_val}\n")
            file.write("\n") # Put new line between sections
            
def get_cardlists(json_data):
    card_lists = {} # Will be dict of lists
    cardlist_json = json_data["container"]["json_dict"]
    commander_name = cardlist_json["card"]["name"]
    card_lists["Commander"] = [commander_name]
    specific_card_lists_data = cardlist_json["cardlists"] # This is list of dicts for some reason
    for cardlist in specific_card_lists_data: # Each cardlist should be a dict with a header of what list it is
        current_cardlist_name = cardlist["header"]
        current_cardlist_cards = []
        for card in cardlist["cardviews"]: # Each card should be dict
            current_card_name = card["name"]
            current_cardlist_cards.append(current_card_name)
        card_lists[current_cardlist_name] = current_cardlist_cards
    flat_cardlist = get_flat_cardlist(card_lists)
    card_lists.update(flat_cardlist)
    return card_lists

def get_cardlist_info(cardlists:dict[list]):
    infos = {"Card Counts": {}} # Will be dict of dicts
    card_counts = infos["Card Counts"]
    for cardlist_name, cardlist in cardlists.items():
        card_counts[cardlist_name] = 0
        for card in cardlist:
            card_counts[cardlist_name] += 1
    print(f"infos['Card Counts'] = {infos['Card Counts']}")
    return infos

def get_flat_cardlist(cardlists:dict):
    flat_cardlist = {"Flat Cardlist": []}
    for cardlist_name, cardlist in cardlists.items():
        for card_name in cardlist:
            flat_cardlist["Flat Cardlist"].append(card_name)
    return flat_cardlist

def get_reduced_cardlists(cardlists: dict[list], card_counts:dict, desired_count:int, safe_lists:list[str]):
    cardlists = cardlists.copy()# Make copy so we don't edit original list
    del cardlists["Flat Cardlist"] # Remove flat cardlist, as we will generate a new one at the end
    if "Commander" not in safe_lists: safe_lists.append("Commander") # Never reduce Commander
    current_count = card_counts["Flat Cardlist"]
    reduce_by = current_count - desired_count
    safe_count = 0
    if safe_lists: # Make sure lists_to_keep isn't empty
        card_counts
        for list_name in safe_lists:
            if list_name in card_counts:
                safe_count += card_counts[list_name]
            else:
                print(f"List name {list_name} not found in card_counts! Double check list name spelling")
                return
    else: 
        print("Nothing entered, please enter cardlist names")
        return
    available_to_reduce = current_count - safe_count
    print(f"safe_count is {safe_count} and available_to_reduce is {available_to_reduce}")
    if available_to_reduce < reduce_by:
        print(f"Can't reduce cards this much with all these lists to keep. Try fewer lists to keep or a higher desired count. available_to_reduce is {available_to_reduce} and reduce_by is {reduce_by} so you need {reduce_by - available_to_reduce} fewer safe cards")
        return
    else:
        choose_factor = (desired_count - safe_count) / available_to_reduce 
        reduced_cardlists = {}
        for cardlist_name in cardlists:
            if cardlist_name in safe_lists:
                reduced_cardlists[cardlist_name] = cardlists[cardlist_name] # Just put the whole list in
            else:
                chosen_cards = []
                num_to_choose = math.ceil(choose_factor * card_counts[cardlist_name])
                unchosen_cards = cardlists[cardlist_name]
                while len(chosen_cards) < num_to_choose:
                    chosen_card = random.choice(unchosen_cards) # Pick a random card
                    unchosen_cards.remove(chosen_card) # Remove that card from the unchosen cards list
                    chosen_cards.append(chosen_card) # Add that card to chosen cards list
                reduced_cardlists[cardlist_name] = chosen_cards
        flat_reduced_cardlist = get_flat_cardlist(reduced_cardlists)
        reduced_cardlists.update(flat_reduced_cardlist)
        return reduced_cardlists
    
def get_list_of_strings_input(instruction:str):
    output = input(instruction)
    if output == "":
        return None
    output_split = output.split(",")
    list_of_strings = [item.strip().lower().title() for item in output_split] # Make it all lowercase then make it title to match cardlist names
    return list_of_strings

def main():
    root = Tk()
    root.attributes("-topmost", True)
    root.iconify() # Hide window
    with open('commander.txt', 'r') as file:
        commander_name = file.read()
        file.close()
    formatted_name = format_commander_name(commander_name)
    json_data = request_json(commander_name)
    cardlists = get_cardlists(json_data)
    output_directory = "./output/" + formatted_name + "/edhrec-suggestions"
    if not os.path.isdir(output_directory):
        os.makedirs(output_directory)
    save_dict_of_lists(cardlists, output_directory)
    cardlist_info = get_cardlist_info(cardlists)
    save_info(cardlist_info, output_directory)
    will_reduce = input("\nWant to make reduced lists? y/n: ")
    if will_reduce == "y":
        desired_count = int(input("\nHow many cards do you want to output? Enter desired total number of cards: "))
        cardlist_options = [key for key in cardlists if not key == "Commander" and not key == "Flat Cardlist"]
        reduced_cardlists = None
        while not reduced_cardlists:
            lists_to_keep = get_list_of_strings_input(f"\nWhich lists do you want to keep? Format is like 'High Synergy Cards, Lands'. Options are: {cardlist_options}: ")
            reduced_cardlists = get_reduced_cardlists(cardlists, cardlist_info["Card Counts"], desired_count, lists_to_keep)
        reduced_cardlists_output_path = browse_output_directory("Select reduced cardlist output directory")
        save_dict_of_lists(reduced_cardlists, reduced_cardlists_output_path)
        reduced_info = get_cardlist_info(reduced_cardlists)
        save_info(reduced_info, reduced_cardlists_output_path)
    else: return
    root.destroy()

if __name__ == "__main__":
    main()
