# Built-in ZHA (Home Assistant 2026.11.1) as a custom integration, with zigpy-znp PR 294

Test build for https://github.com/zigpy/zigpy-znp/pull/294. It is an unmodified copy of `homeassistant/components/zha` from Home Assistant tag 2026.11.1. The only changes are in `manifest.json`: a `version` key (custom integrations need one) and a `zigpy-znp` requirement pinned to commit 411f95a of the PR branch. Home Assistant installs that requirement at startup.

Install: copy `custom_components/zha` into `<config>/custom_components/zha`, restart Home Assistant. Remove the folder and restart to go back to the built-in ZHA. Only for Home Assistant 2026.11.x, the copy must match the core version.
