Go project rules:
- Tests: `go test -count=1 ./...` (`-count=1` defeats caching — always fresh)
- Lint: `go vet ./...`
- Format: `gofmt -w .`
- Test fails → read the output, fix the code, rerun
