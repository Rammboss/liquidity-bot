import json
import os


class AbiService:
  def __init__(self, abi_dir="./abis"):
    self.abi_dir = abi_dir
    self.cache = {}

  def get_abi(self, filename):
    """Loads and caches ABI from a JSON file."""
    if filename in self.cache:
      return self.cache[filename]

    # Ensure the filename ends with .json
    if not filename.endswith(".json"):
      filename += ".json"

    filepath = os.path.join(self.abi_dir, filename)

    try:
      with open(filepath, 'r') as f:
        abi = json.load(f)
        self.cache[filename] = abi
        return abi
    except FileNotFoundError:
      raise FileNotFoundError(f"ABI file not found: {filepath}")
    except json.JSONDecodeError:
      raise ValueError(f"Invalid JSON format in: {filepath}")
