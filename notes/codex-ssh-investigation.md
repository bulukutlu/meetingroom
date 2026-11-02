# Codex over SSH: confirmed host sandbox failure

**Direct reproduction on biollante:** Bubblewrap fails before the requested command runs. This reproduces outside Meeting Room, independently of Codex and the project’s files.

```text
$ bwrap --unshare-user --uid 0 --gid 0 --ro-bind / / /bin/true
bwrap: setting up uid map: Permission denied
```

| Check | Observed result |
| --- | --- |
| SSH connection and ordinary shell commands | Work |
| Remote OS | Ubuntu 24.04.5 LTS; Linux 7.0.0-38-generic |
| Bubblewrap | /usr/bin/bwrap, version 0.9.0 |
| Unprivileged user namespaces enabled | 1 |
| AppArmor restriction on unprivileged user namespaces | 1 |
| Dedicated Bubblewrap AppArmor profile | Not found at /etc/apparmor.d/bwrap-userns-restrict |
| Meeting logs | Both Codex participants report the same UID mapping failure |

The evidence points to the host’s user-namespace/AppArmor configuration. The exact denying rule has not been confirmed from privileged audit logs. Ordinary remote execution succeeds because it does not need to create Codex’s sandbox.

## Recommended repair

Have the host administrator install/load the Bubblewrap AppArmor profile, preserving the sandbox. The official OpenAI documentation gives this Ubuntu 24.04 procedure:

```sh
sudo apt update
sudo apt install apparmor-profiles apparmor-utils
sudo install -m 0644 \
  /usr/share/apparmor/extra-profiles/bwrap-userns-restrict \
  /etc/apparmor.d/bwrap-userns-restrict
sudo apparmor_parser -r /etc/apparmor.d/bwrap-userns-restrict
```

Check that the source profile exists after installation. Then repeat the Bubblewrap command above; exit 0 is the first acceptance check. Finally, start a fresh remote Codex turn, create/read/remove a temporary file within the chosen project, and execute a trivial script. Those Codex acceptance checks remain pending.

[Official OpenAI documentation: sandbox prerequisites and Ubuntu AppArmor setup](https://learn.chatgpt.com/docs/sandboxing)

## App behavior that also needs attention

| Finding in current code | Consequence / proposed change |
| --- | --- |
| SSH Test checks executable discovery, not sandbox startup (`location.py:probe`) | It can report success while every Codex command will fail. Add a Codex sandbox readiness check and show the actual failure. |
| Codex always uses `approval_policy="never"` (`agents.py:CodexBackend._cmd`) | A denied action cannot escalate through a room approval card. |
| Auto-run changes `agent.approval`, which Codex launch ignores | The control cannot fix a Codex sandbox failure. Make its behavior provider-aware; integrating approvals requires a real approval channel. |
| Remote Codex discards `add_dirs` (`agents.py:CodexBackend.__init__`) | Additional writable directories are unavailable remotely. Support explicitly configured remote paths. This is separate from the UID mapping failure. |

The existing `sandbox` agent setting permits an explicitly chosen full-access mode, but that removes filesystem and network isolation. It is not needed to diagnose this failure; repairing Bubblewrap is the preferred path.

**Scope:** Read-only remote diagnostics completed. No host settings, agent permissions, or application source were changed. This report does not claim the remote Codex workflow is repaired.
