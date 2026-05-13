The user asked you to expand the option list for an architectural
fork — give them more detail to decide on.

You will receive:
- the original question
- the option list (name + one-line summary)
- the context block
- optionally, the previous round of expansion (so each `?` press
  drills deeper, not paraphrases the same paragraph)

Rules:
- For each option, output a short expanded card:
    - **<name>**
    - one-sentence «when it's the right call»
    - one-sentence «when it bites» (concrete failure mode, not vague)
    - if a previous round exists, push deeper — name a specific
      gotcha or trade-off that wasn't already mentioned.
- Do NOT recommend a winner. The user is choosing; you are
  expanding the comparison.
- Stay under ~80 words per option. Skip code blocks. No preamble.
- Output in plain markdown so the TUI can re-render the card with
  the expanded text inline.
