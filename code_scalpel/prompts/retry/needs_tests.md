Your previous patch applied cleanly and the existing tests pass, but it
changed production code without touching any test file. Produce a
follow-up `write_file` that adds a test exercising the new behaviour.
Put it under `tests/`, name it `test_<feature>.py`, and keep the
existing patch on disk — only add.

The test must actually exercise the new behaviour — call the new
function, assert on its real output. A test that just asserts True is
not acceptable; it doesn't test anything.
