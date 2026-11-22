# Release notes

This repository has no tagged or published releases yet. Keep changes under
**Unreleased** until the first release version is chosen and published.

## Unreleased

### Python runtime

- Use Python 3.14 (currently 3.14.10) for Windows source and executable builds,
  preserving offline Whisper support while moving beyond the previous 3.11–3.13
  limit. CI now includes Python 3.14.

### Windows delivery

- Rename the application folder to `Adhithiya AI-main` and align project and CI
  paths with the new name.
- Add a Windows source launcher (`run_adhithiya.bat`) and a Windows-only build
  path (`build_windows.bat`, `ADHITHIYA-windows.spec`) for a single-file
  `ADHITHIYA.exe`.
- Add a Windows GitHub Actions workflow that builds the executable and uploads
  it as an `ADHITHIYA-Windows` workflow artifact. This is a CI artifact, not a
  published release asset or installer.
- Route system speech through Windows SAPI and add regression coverage for
  platform-specific speech routing and packaging support.

### Provider setup

- Add provider selection from recognized API-key formats and explicit support
  for Groq, OpenAI, and OpenAI-compatible gateways.
- Preserve gateway URL and API-key configuration, with an optional gateway
  model override. A custom or unrecognized key may require an explicit provider
  selection; multiple configured provider keys also require an explicit choice.
- Provider model defaults remain in effect; this change does not add automatic
  model discovery.

### Documentation

- Refresh the README and architecture documentation for the folder rename,
  provider/key setup, gateway configuration, and Windows source and `.exe`
  workflows.
