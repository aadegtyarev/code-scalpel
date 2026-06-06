# Python Notes CLI

A small Python command-line tool for managing notes stored in a JSON file.

## Commands

- `add`: add a new note.
  - Example: `notes-cli add "Buy milk"`
- `list`: show all saved notes.
  - Example: `notes-cli list`
- `search`: find notes containing a query string.
  - Example: `notes-cli search milk`
- `delete`: remove a note by its identifier.
  - Example: `notes-cli delete 3`

## Storage

Notes are persisted in a JSON file on disk. The storage file contains a JSON array of note objects. Each note should include at least:

- `id`: a unique identifier
- `text`: the note content
- `created_at`: timestamp of creation

The CLI reads and writes the same storage file across runs so notes survive process restarts.
