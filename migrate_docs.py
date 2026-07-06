import os
import re
from pathlib import Path

# More robust regex replacements to catch remaining instances
regex_replacements = [
    (r'(?i)microalgos?', 'motes'),
    (r'(?i)algosdk', 'casper-js-sdk'),
    (r'(?i)algoNode', 'CasperNode'),
    (r'(?i)algod', 'casper-rpc'),
    (r'(?i)Nodely', 'CSX'),
    (r'(?i)algorand', 'Casper Network'),
    (r'(?i)algo', 'CSPR'),
    (r'(?i)pera\s*wallet', 'Casper Wallet'),
    (r'(?i)pera', 'Casper'),
    (r'(?i)pyteal', 'Rust WASM'),
    (r'(?i)teal', 'WASM'),
]

def replace_in_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        new_content = content
        for pattern, new in regex_replacements:
            new_content = re.sub(pattern, new, new_content)
            
        if new_content != content:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(new_content)
            print(f"Updated: {filepath}")
    except Exception as e:
        print(f"Error processing {filepath}: {e}")

def main():
    directories = ["docs", "tests"]
    for d in directories:
        dir_path = Path(d)
        if dir_path.exists():
            for root, _, files in os.walk(dir_path):
                for file in files:
                    if file.endswith('.md') or file.endswith('.csv'):
                        filepath = Path(root) / file
                        replace_in_file(filepath)

if __name__ == "__main__":
    main()
