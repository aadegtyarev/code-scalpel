# Python CLI for Notes

This project provides a simple command-line interface (CLI) for managing notes. The CLI supports the following commands:

- **add**: Add a new note.
  ```bash
  python notes.py add "Your note text here"
  ```

- **list**: List all notes.
  ```bash
  python notes.py list
  ```

- **search**: Search for notes containing a specific keyword.
  ```bash
  python notes.py search "keyword"
  ```

- **delete**: Delete a note by its index.
  ```bash
  python notes.py delete <index>
  ```

## Data Storage

Notes are stored in a JSON file named `notes.json` within the project directory.