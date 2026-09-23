# Source acquisition (T05)

Status: native T05 acceptance complete; full container acceptance remains open. See the acceptance ledger and project status for executed evidence.

## Runtime configuration

The indexer uses an explicitly configured, trusted Git executable (`REPOSCOPE_GIT_BINARY`) and an absolute private durable storage root (`REPOSCOPE_SOURCE_ROOT`). The Compose indexer mounts `source-data` at `/var/lib/reposcope/sources`; only this role joins the source egress network. Database, broker, Redis and worker health ports remain unpublished. Do not mount the storage root inside an imported repository.

Public admission accepts canonical public GitHub HTTPS identities. It does not accept arbitrary hosts, credentials, local paths or operator import roots. Source acquisition does not execute repository code, build commands, hooks, submodules or LFS programs. A pinned commit is retained across retries.

## Stage semantics

Acquisition produces a deterministic manifest and immutable source blobs for the later indexing stage. The source continuation is `repo.source.acquired`; it contains scoped identifiers, the pinned commit, the manifest digest and the source policy version, not source text. Its canonical schema is generated from `contracts/models.py`.

Source acquisition is not a ready index. T06 will consume the durable continuation and build the index. A staged job remains subject to its original overall deadline; a completed acquisition must not be rerun merely because later indexing is unfinished. Runs still require an owned ready generation.

## Limits and exclusions

The defaults are 1 MiB per eligible file, 20,000 eligible files, 250 MiB of eligible content, a 1 GiB monitored temporary disk budget and a 120-second acquisition deadline. Directory entries and command output have separate bounds. Known secret paths, generated/vendor trees, binary or non-UTF-8 content, symlinks, submodules and LFS pointer files are excluded or rejected according to the source policy. Filename rules are not a general-purpose secret detector for arbitrarily misnamed files.

Download accounting uses a controlled localhost CONNECT tunnel restricted to approved public GitHub addresses. Git still verifies the GitHub TLS hostname. The shared acquisition allowance counts TLS transport payload in both directions, including protocol overhead, across commands; it is not an estimate from pack-file size. No application byte beyond the allowance is forwarded. At most one extra byte is read to detect overflow; kernel receive buffering is outside that application limit.

Disk monitoring can detect and terminate growth after a transient overshoot; it is not an instantaneous filesystem quota. Its detection latency includes the bounded directory scan. Windows processes use owned Job Objects; POSIX processes use owned process groups. Termination must include descendants even when their parent has exited.

Manifests contain sorted file paths, content hashes and sizes, skip counts, source identity, commit identity for Git sources, policy version, and license-file hashes. Unrecognized license terms remain `unknown`. A license file's presence is not proof of permission for every file.

## Operator-only local snapshots

Prepare a quiescent directory under a trusted import root. Stop other writers before importing. Roots and their ancestors must be ordinary operator-owned directories; imported links, reparse points and hardlinks are not accepted. This interface is not exposed through HTTP.

From the project root, using the project's Python environment:

```text
python scripts/import_local_source.py --import-root ABSOLUTE_IMPORT_ROOT --source-root ABSOLUTE_STORAGE_ROOT --name sample
```

The runtime image includes this operator command. For a container import, mount the chosen host staging directory read-only at an explicit import root and pass that root with `--import-root`; it is not mounted by the default Compose file. Container execution remains subject to the open Docker acceptance gate.

`sample` must be one directory name directly under the import root. The command prints only a storage key, manifest digest, file/byte counts and skip counts. It creates a snapshot; it does not create a database job or claim that an index is ready. A local snapshot has a `local:` identity and no fabricated Git commit SHA.

The operator is responsible for choosing sources they are authorized to import. Local source content stays in the configured storage root and is not added to the project or its handoff package.

## Verification boundary

Unit tests, native PostgreSQL/NATS tests, actual public-GitHub acquisition, and container acceptance are distinct evidence. Native checks do not prove the pinned Linux images build or run. The prior Docker/WSL acceptance gate remains open until executed in a suitable environment.
