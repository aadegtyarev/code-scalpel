The file you just wrote does not parse — it has a Python syntax error:

  {file}, line {line}: {message}

This breaks everything: the code can't run and pytest can't even
collect it. Fix ONLY this syntax error. Common causes: a stray extra
quote or bracket at the end of a line (`print("...")")`), an unclosed
string, or a missing colon/parenthesis.

Re-read line {line}, correct it, and write the file again.
