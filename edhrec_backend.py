import json
import os
import requests
import re
from datetime import datetime
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import argparse

try:
    from tkinter import Tk
    TK_AVAILABLE = True
except Exception:
    TK_AVAILABLE = False

# Scryfall rejects requests.get()'s default User-Agent with a 400
# ("generic_user_agent") -- https://scryfall.com/docs/api requires a
# custom one identifying the calling app.
SCRYFALL_HEADERS = {
    "User-Agent": "edhrec-deck-analyzer/1.0 (+https://github.com/spicyFajitas/edhrec-deck-building-scripts)",
    "Accept": "application/json",
}


########################
# EDHRec Analyzer Class
########################

class EDHRecAnalyzer:
    def __init__(self):
        # Rate limiting
        self.last_scryfall_request = 0
        self.last_edhrec_request = 0
        self.SCRYFALL_MIN_DELAY = 0.12   # Scryfall: 50–100ms requested
        self.EDHREC_MIN_DELAY = 0.80     # EDHREC safe delay

        # Build ID cache
        self.build_id = None

        # Cache paths
        self.cache_root = "./cache"
        self.deck_cache_dir = os.path.join(self.cache_root, "deck_cache")
        self.scryfall_cache_path = os.path.join(self.cache_root, "scryfall_cache.json")
        self.history_path = os.path.join(self.cache_root, "search_history.json")

        os.makedirs(self.cache_root, exist_ok=True)
        os.makedirs(self.deck_cache_dir, exist_ok=True)

        # Scryfall cache
        self.scryfall_cache = self.load_scryfall_cache()

        # In-memory only: commander typeahead results for this process's
        # lifetime. Cheap to regenerate, not worth persisting to disk.
        self.commander_search_cache = {}

    #################
    # Rate limiting
    #################

    def rate_limit_scryfall(self):
        elapsed = time.time() - self.last_scryfall_request
        if elapsed < self.SCRYFALL_MIN_DELAY:
            time.sleep(self.SCRYFALL_MIN_DELAY - elapsed)
        self.last_scryfall_request = time.time()

    def rate_limit_edhrec(self):
        elapsed = time.time() - self.last_edhrec_request
        if elapsed < self.EDHREC_MIN_DELAY:
            time.sleep(self.EDHREC_MIN_DELAY - elapsed)
        self.last_edhrec_request = time.time()

    #################
    # Format Helpers
    #################

    @staticmethod
    def format_commander_name(commander_name: str):
        non_alphas_regex = r"[^\w\s]"
        formatted_name = re.sub(non_alphas_regex, "", commander_name)
        formatted_name = formatted_name.lower()
        formatted_name = formatted_name.replace(" ", "-")
        formatted_name = formatted_name.replace("'", "")
        return formatted_name

    ###########################
    # Build Manifest Fetching #
    ###########################

    def fetch_edhrec_build_id(self):
        """
        Fetches the EDHREC build ID by parsing the homepage HTML and extracting:
        /_next/static/<BUILD_ID>/_buildManifest.js
        """
        if self.build_id:
            return self.build_id

        self.rate_limit_edhrec()
        r = requests.get("https://edhrec.com")
        if r.status_code != 200:
            raise Exception("Failed to load EDHREC homepage to detect build ID")

        html = r.text

        marker = "_buildManifest.js"
        idx = html.find(marker)
        if idx == -1:
            raise Exception("Could not find _buildManifest.js reference in homepage.")

        prefix = html[:idx]

        static_marker = "/_next/static/"
        static_idx = prefix.rfind(static_marker)
        if static_idx == -1:
            raise Exception("Could not locate /_next/static/ in homepage.")

        start = static_idx + len(static_marker)
        end = prefix.find("/", start)
        build_id = prefix[start:end]

        if not build_id or len(build_id) < 5:
            raise Exception(f"Extracted invalid EDHREC build ID: '{build_id}'")

        self.build_id = build_id
        print(f"[INFO] EDHREC build ID detected: {build_id}")
        return build_id

    ##########################
    # Output Directory Cleanup
    ##########################

    def clean_output_directories(self, formatted_name: str):
        output_dir = os.path.join("./output", formatted_name, "edhrec-decklists")

        if os.path.exists(output_dir):
            for f in os.listdir(output_dir):
                try:
                    os.remove(os.path.join(output_dir, f))
                except Exception:
                    pass
        else:
            os.makedirs(output_dir, exist_ok=True)

        print(f"Output directory cleaned: {output_dir}")
        return output_dir

    ##############################
    # EDHREC Deck Table Functions
    ##############################

    def fetch_deck_table(self, commander_formatted: str):
        url = f"https://json.edhrec.com/pages/decks/{commander_formatted}.json"

        self.rate_limit_edhrec()
        r = requests.get(url)

        if r.status_code != 200:
            raise Exception(f"Failed to fetch deck table: HTTP {r.status_code}")

        return r.json()

    ###################################
    # Deck Filtering (price + recency)
    ###################################

    @staticmethod
    def filter_deck_hashes(deck_table: dict, recent: int, min_price: float, max_price: float):
        entries = deck_table["table"]

        for e in entries:
            e["savedate_dt"] = datetime.strptime(e["savedate"], "%Y-%m-%d")

        sorted_entries = sorted(entries, key=lambda e: e["savedate_dt"], reverse=True)

        filtered = [
            e for e in sorted_entries
            if min_price <= e["price"] <= max_price
        ]

        limited = filtered[:recent]
        return [e["urlhash"] for e in limited]

    ##################################
    # Persistent Deck Cache Functions
    ##################################

    @staticmethod
    def _normalize_deck(raw):
        """Convert either API deck format to a flat ["qty CardName", ...] list.

        Old format (pre-2026-08): list of strings like "1 Sol Ring"
        New format (2026-08+):    dict with 'commander_v2' and 'cards' keys
        """
        if isinstance(raw, list):
            return raw
        if not isinstance(raw, dict):
            return None
        lines = []
        for entry in raw.get("commander_v2", []):
            name, qty = (entry[0], entry[1]) if len(entry) == 2 else (entry[0], 1)
            lines.append(f"{qty} {name}")
        for type_list in raw.get("cards", {}).values():
            for entry in type_list:
                name, qty = (entry[0], entry[1]) if len(entry) == 2 else (entry[0], 1)
                lines.append(f"{qty} {name}")
        return lines

    def load_deck_from_cache(self, deck_id):
        path = os.path.join(self.deck_cache_dir, deck_id + ".json")
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    raw = json.load(f)
                # Cache may contain old dict format from before the API change;
                # normalize so callers always get a flat list.
                return self._normalize_deck(raw)
            except Exception:
                return None
        return None

    def save_deck_to_cache(self, deck_id, deck):
        path = os.path.join(self.deck_cache_dir, deck_id + ".json")
        with open(path, "w") as f:
            json.dump(deck, f, indent=2)

    ###############################
    # EDHREC Deck Fetching (API)
    ###############################

    def fetch_deck_by_hash(self, deck_id: str):
        cached = self.load_deck_from_cache(deck_id)
        if cached:
            return cached

        if not self.build_id:
            self.fetch_edhrec_build_id()

        self.rate_limit_edhrec()
        url = f"https://edhrec.com/_next/data/{self.build_id}/deckpreview/{deck_id}.json?deckId={deck_id}"
        r = requests.get(url)

        if r.status_code != 200:
            print(f"Failed to fetch deck {deck_id} - HTTP {r.status_code}")
            return None

        try:
            raw = r.json()["pageProps"]["data"]["deck"]
        except KeyError:
            print(f"Deck JSON format unexpected for {deck_id}")
            return None

        deck = self._normalize_deck(raw)
        if deck is None:
            print(f"Deck JSON format unexpected for {deck_id}")
            return None

        self.save_deck_to_cache(deck_id, deck)
        return deck

    #########################################
    # Parallel Deck Downloader (Rate-Aware)
    #########################################

    def fetch_decks_with_progress(self, deck_hashes):
        """
        Generator that yields (completed, total, deck)
        Safe for Streamlit progress bars.
        """
        total = len(deck_hashes)
        completed = 0

        if not deck_hashes:
            return

        max_workers = min(5, len(deck_hashes))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self.fetch_deck_by_hash, deck_id): deck_id
                for deck_id in deck_hashes
            }

            for future in as_completed(futures):
                deck = None
                try:
                    deck = future.result()
                except Exception as e:
                    print(f"Error fetching deck {futures[future]}: {e}")

                completed += 1
                yield completed, total, deck


    ####################
    # Scryfall Caching
    ####################

    def load_scryfall_cache(self):
        if os.path.exists(self.scryfall_cache_path):
            try:
                with open(self.scryfall_cache_path, "r") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_scryfall_cache(self):
        with open(self.scryfall_cache_path, "w") as f:
            json.dump(self.scryfall_cache, f, indent=2)

    def get_card_type(self, card_name: str):
        cached = self.scryfall_cache.get(card_name)

        # -------------------------------
        # NEW: handle old cache format
        # -------------------------------
        if isinstance(cached, dict):
            return cached["type_line"]

        # Old cache format (string only)
        if isinstance(cached, str):
            return cached

        # Not cached at all
        meta = self._fetch_scryfall_metadata(card_name)
        if meta is None:
            return "Unknown"
        self.scryfall_cache[card_name] = meta
        self.save_scryfall_cache()
        return meta["type_line"]

    def _fetch_scryfall_metadata(self, card_name: str):
        """Returns the metadata dict on success, or None on failure.

        Failures (rate limiting, transient errors) are intentionally not
        cached by callers so a card can be retried on a later lookup
        instead of being stuck as "Unknown" forever.
        """
        self.rate_limit_scryfall()

        url = f"https://api.scryfall.com/cards/named?exact={card_name}"
        r = requests.get(url, headers=SCRYFALL_HEADERS)

        if r.status_code != 200:
            return None

        card = r.json()
        type_line = card.get("type_line", "Unknown")
        scryfall_uri = card.get("scryfall_uri")

        image_url = None
        # normal single-face images
        if isinstance(card.get("image_uris"), dict):
            image_url = card["image_uris"].get("normal")

        # double-faced / split / transform cards
        if not image_url and isinstance(card.get("card_faces"), list) and card["card_faces"]:
            face0 = card["card_faces"][0]
            if isinstance(face0.get("image_uris"), dict):
                image_url = face0["image_uris"].get("normal")

        return {"type_line": type_line, "image_url": image_url, "scryfall_uri": scryfall_uri}

    # ✅ NEW: minimal add-on for images + link
    def get_card_metadata(self, card_name: str):
        """
        Returns:
          {
            "type_line": str,
            "image_url": str|None,
            "scryfall_uri": str|None
          }

        Backward compatible with existing cache:
          - if cache contains a string, it will be treated as type_line.
          - we may upgrade to dict once we fetch metadata.
        """
        if card_name in self.scryfall_cache:
            cached = self.scryfall_cache[card_name]
            if isinstance(cached, dict):
                return {
                    "type_line": cached.get("type_line", "Unknown"),
                    "image_url": cached.get("image_url"),
                    "scryfall_uri": cached.get("scryfall_uri"),
                }
            # cached is the old string type_line
            return {
                "type_line": cached,
                "image_url": None,
                "scryfall_uri": None,
            }

        meta = self._fetch_scryfall_metadata(card_name)
        if meta is None:
            return {"type_line": "Unknown", "image_url": None, "scryfall_uri": None}

        # store dict format (upgrade path)
        self.scryfall_cache[card_name] = meta
        self.save_scryfall_cache()
        return meta

    ####################################
    # Commander Search (typeahead)
    ####################################

    def search_commander_names(self, query: str, limit: int = 8):
        """
        Returns up to `limit` legal-commander card names matching `query`
        (substring match against card name), via Scryfall's search API.
        Short queries return no results to avoid a network call on every
        single character typed.
        """
        query = query.replace('"', "").strip()
        if len(query) < 2:
            return []

        if query in self.commander_search_cache:
            return self.commander_search_cache[query]

        self.rate_limit_scryfall()

        try:
            r = requests.get(
                "https://api.scryfall.com/cards/search",
                headers=SCRYFALL_HEADERS,
                params={"q": f'is:commander name:"{query}"', "order": "name"},
                timeout=5,
            )
        except requests.RequestException:
            return []

        # Scryfall returns 404 for zero matches; anything else just
        # yields no suggestions rather than surfacing an error to the UI.
        results = [card["name"] for card in r.json().get("data", [])[:limit]] if r.status_code == 200 else []

        self.commander_search_cache[query] = results
        return results

    ###################################
    # Deck Processing (Card Counting)
    ###################################

    @staticmethod
    def count_cards(all_decks):
        card_counts = {}

        for deck in all_decks:
            for line in deck:
                try:
                    qty_str, card_name = line.split(" ", 1)
                    qty = int(qty_str)
                except ValueError:
                    continue

                card_counts[card_name] = card_counts.get(card_name, 0) + qty

        return card_counts

    def group_cards_by_type(self, card_counts):
        type_groups = {
            "Creature": {},
            "Instant": {},
            "Sorcery": {},
            "Artifact": {},
            "Enchantment": {},
            "Planeswalker": {},
            "Battle": {},
            "Land": {},
            "Unknown": {}
        }

        for card, count in tqdm(card_counts.items(), desc="Classifying card types"):
            type_line = self.get_card_type(card)

            matched = False
            for t in type_groups:
                if t != "Unknown" and t in type_line:
                    type_groups[t][card] = count
                    matched = True
                    break

            if not matched:
                type_groups["Unknown"][card] = count

        return type_groups

    ###########################################
    # Embedded metadata (header in every file)
    ###########################################

    @staticmethod
    def build_metadata_header(commander_name, recent, min_price, max_price, source_info):
        header = []
        header.append("Commander Run Metadata")
        header.append("======================")
        header.append("")
        header.append(f"Timestamp: {datetime.now()}")
        header.append(f"Commander: {commander_name}")
        header.append(f"Max Decks: {recent}")
        header.append(f"Min Price: {min_price}")
        header.append(f"Max Price: {max_price}")
        header.append(f"Input Source: {source_info}")
        header.append("")
        header.append("Results")
        header.append("======")
        header.append("")
        return "\n".join(header)

    ###########################################
    # Saving Output (Master list + type lists)
    ###########################################

    @staticmethod
    def save_master_cardcount(card_counts, output_directory, metadata_header=""):
        sorted_cards = sorted(card_counts.items(), key=lambda x: x[1], reverse=True)

        with open(os.path.join(output_directory, "master_card_counts.txt"), "w") as f:
            if metadata_header:
                f.write(metadata_header + "\n")
            for card, count in sorted_cards:
                f.write(f"{count}  {card}\n")

    @staticmethod
    def save_cardtypes(type_groups, output_directory, metadata_header=""):
        for type_name, cards in type_groups.items():
            if not cards:
                continue

            filename = f"cards_{type_name.lower()}.txt"
            path = os.path.join(output_directory, filename)

            sorted_cards = sorted(cards.items(), key=lambda x: x[1], reverse=True)

            with open(path, "w") as f:
                if metadata_header:
                    f.write(metadata_header + "\n")
                for card, count in sorted_cards:
                    f.write(f"{count}  {card}\n")

    @staticmethod
    def save_decklists(all_decks, output_directory, formatted_name, metadata_header=""):
        decklist_path = os.path.join(output_directory, formatted_name + "-decklists.txt")
        with open(decklist_path, "w") as f:
            if metadata_header:
                f.write(metadata_header + "\n")
            for d in all_decks:
                f.write("\n".join(d))
                f.write("\n\n")
        return decklist_path

    ###################################
    # Search History
    ###################################

    def load_search_history(self):
        if os.path.exists(self.history_path):
            try:
                with open(self.history_path, "r") as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def save_search_history(
        self, commander_name, formatted_name, recent, min_price, max_price,
        deck_count, card_count, max_entries: int = 50,
    ):
        entry = {
            "commander_name": commander_name,
            "formatted_name": formatted_name,
            "recent": recent,
            "min_price": min_price,
            "max_price": max_price,
            "deck_count": deck_count,
            "card_count": card_count,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        history = self.load_search_history()
        history.append(entry)
        history = history[-max_entries:]
        with open(self.history_path, "w") as f:
            json.dump(history, f, indent=2)
        return history


####################
# argument parsing #
####################

def parse_inputs():
    parser = argparse.ArgumentParser(
        description="EDHREC deck fetcher (CLI args optional)",
        add_help=True
    )

    parser.add_argument("--commander", type=str, help="Override commander name")
    parser.add_argument("--recent", type=int, help="Number of recent decks to use")
    parser.add_argument("--min-price", type=float, help="Minimum deck price")
    parser.add_argument("--max-price", type=float, help="Maximum deck price")

    args = parser.parse_args()

    # print usage help if NO CLI args at all
    if not any(vars(args).values()):
        print("\n--- Command Line Usage (optional) ---")
        print("python3 edhrec_backend.py --recent 20 --min-price 200 --max-price 450")
        print("Commander name is always read from commander.txt unless overridden.\n")
        print("No CLI arguments detected — falling back to interactive prompts.\n")

    # Commander defaults to file unless overridden
    if args.commander:
        commander_name = args.commander
    else:
        with open("commander.txt", "r") as f:
            commander_name = f.read().strip()

    # If CLI supplied, use it; otherwise prompt
    if args.recent is not None:
        recent = args.recent
    else:
        recent = int(input("How many recent decks to use?: "))

    if args.min_price is not None:
        min_price = args.min_price
    else:
        min_price = float(input("Minimum deck price?: "))

    if args.max_price is not None:
        max_price = args.max_price
    else:
        max_price = float(input("Maximum deck price?: "))

    source_info = {
        "commander": "CLI" if args.commander else "file",
        "recent": "CLI" if args.recent is not None else "prompt",
        "min_price": "CLI" if args.min_price is not None else "prompt",
        "max_price": "CLI" if args.max_price is not None else "prompt"
    }

    return commander_name, recent, min_price, max_price, source_info


############################
# Module-level convenience #
############################

_analyzer = EDHRecAnalyzer()

def format_commander_name(commander_name: str):
    return _analyzer.format_commander_name(commander_name)

def fetch_edhrec_build_id():
    return _analyzer.fetch_edhrec_build_id()

def clean_output_directories(formatted_name: str):
    return _analyzer.clean_output_directories(formatted_name)

def fetch_deck_table(commander_formatted: str):
    return _analyzer.fetch_deck_table(commander_formatted)

def filter_deck_hashes(deck_table: dict, recent: int, min_price: float, max_price: float):
    return _analyzer.filter_deck_hashes(deck_table, recent, min_price, max_price)

def fetch_decks_with_progress(deck_hashes):
    return _analyzer.fetch_decks_with_progress(deck_hashes)

def count_cards(all_decks):
    return _analyzer.count_cards(all_decks)

def group_cards_by_type(card_counts):
    return _analyzer.group_cards_by_type(card_counts)

def save_master_cardcount(card_counts, output_directory, metadata_header=""):
    return _analyzer.save_master_cardcount(card_counts, output_directory, metadata_header)

def save_cardtypes(type_groups, output_directory, metadata_header=""):
    return _analyzer.save_cardtypes(type_groups, output_directory, metadata_header)

def save_decklists(all_decks, output_directory, formatted_name, metadata_header=""):
    return _analyzer.save_decklists(all_decks, output_directory, formatted_name, metadata_header)


########
# MAIN #
########

def main():
    if TK_AVAILABLE:
        root = Tk()
        root.attributes("-topmost", True)
        root.iconify()
    else:
        root = None

    commander_name, recent, min_price, max_price, source_info = parse_inputs()

    formatted_name = _analyzer.format_commander_name(commander_name)
    output_directory = _analyzer.clean_output_directories(formatted_name)

    _analyzer.fetch_edhrec_build_id()
    deck_table = _analyzer.fetch_deck_table(formatted_name)

    deck_hashes = _analyzer.filter_deck_hashes(deck_table, recent, min_price, max_price)
    print(f"Using {len(deck_hashes)} deck hashes")

    # NOTE: CLI path in your original code referenced fetch_decks_parallel() which isn't defined.
    # Left untouched as requested.

    if root:
        root.destroy()


if __name__ == "__main__":
    main()
