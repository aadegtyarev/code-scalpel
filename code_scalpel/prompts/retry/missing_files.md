The following file(s) do not exist yet: {paths}

STOP calling read_file on these paths — they are confirmed missing.
Create each one NOW with the `write_file` tool. One call per file,
pass the full content as the `content` argument.

Example: write_file({{"path": "requirements.txt", "content": "requests\nprettytable\n"}})

Emit the write_file call(s) in your next turn. No read_file on these paths.
