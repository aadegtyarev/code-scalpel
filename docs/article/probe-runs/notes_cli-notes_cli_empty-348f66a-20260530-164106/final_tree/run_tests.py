import os
import subprocess

def run_test(file):
    result = subprocess.run(['pytest', file], capture_output=True, text=True)
    print(result.stdout)
    print(result.stderr)
    return result.returncode == 0

if __name__ == '__main__':
    test_files = ['tests/test_add.py', 'tests/test_list.py', 'tests/test_search.py', 'tests/test_delete.py']
    all_passed = True
    for file in test_files:
        if not run_test(file):
            all_passed = False
    exit(0 if all_passed else 1)