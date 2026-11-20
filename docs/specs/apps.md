# Applications

FA1 adds applications of its own to the control plane. Each one is a sibling of Robinauts and
neorc: an icon on the rail of the App tab, and an API of its own on the control plane.

| application | shows | keeps |
|---|---|---|
| `reviews` | one panel, a placeholder: "something to review" | `reviews.db`: one table, empty |

## FA1 is the host

oneberth composes applications for a host: the program that gives it the list of components,
and the list of the rail. FA1 is the host of its control plane. Robinauts and neorc are two of
its parts.

| list | file | gives oneberth |
|---|---|---|
| the backend's | `apps/backend.py` | Robinauts' component, neorc's, then FA1's, to `compose_app` |
| the rail's | `apps/main.tsx` | Robinauts' application, neorc's, then FA1's, to `Shell` |

- Robinauts gives its parts to a host. `robinauts_parts` returns its component and neorc's,
  wired. `@robinauts/ui` exports `robinautsApp()` and `neorcWithForms()`
  ([core.md](core.md), "What FA1 takes from Robinauts").
- Robinauts knows nothing of FA1's applications. A new application changes the two lists.
- oneberth's shell catches an application that throws. `main.tsx` wraps the shell in FA1's
  fallback page, which shows the failure and a reload when the shell itself throws.

## The folder

`apps/` in this repository holds the host and the applications, one folder each.

```
apps/
    backend.py                   the backend's list
    main.tsx                     the rail's list
    Fallback.tsx, fallback.css   the page a shell that throws leaves
    <name>/
        backend.py               the API: a oneberth component, and the records
        index.tsx                the name, the title, the icon, the loader of the root component
    Dockerfile                   the image of `control`
    package.json, package-lock.json, vite.config.ts, tsconfig.json, index.html
                                 the interface's build
    vendor.sh                    Robinauts' interface and its peers, as node packages
```

- The app holds these files, and writes them to `compose/apps/` in its folder at each start.
- A start writes that folder anew. A file a release dropped goes too.

## The image

`control` is built from `apps/Dockerfile`, with Robinauts at the pinned commit as the build
context `robinauts` ([containers.md](containers.md)). It has three stages.

1. **The packages.** `vendor.sh` runs Robinauts' `scripts/robinauts-ui-pack.sh`, and unpacks
   `@robinauts/ui`, `@neorc/ui` and `@oneberth/ui` into `vendor/`.
2. **The interface.** `npm ci` installs from `package-lock.json`, and `npm run build` checks
   the types and builds `main.tsx` into `dist/`.
3. **The backend.** `uv sync --locked` installs Robinauts from its lock, as its own image does.
   The image then holds `apps/` and `dist/`, and starts `backend.py`.

A change to `apps/` is a new image of `control`. The next start builds it and starts `control`
anew.

## The interface's dependencies

- The interface has a lock of its own, `apps/package-lock.json`. Every package of the registry
  in it is at the version and the hash of Robinauts' own lock.
- The three vendored packages are folders. The pinned commit fixes their content, and the lock
  holds no hash of them.
- Robinauts' build gates read Robinauts' own bundle. FA1's bundle has no licence gate, no size
  budget and no audit yet.

To move the lock with the pin, in a checkout of Robinauts at the pinned commit:

```sh
apps/vendor.sh <the checkout>
cp <the checkout>/frontend/package-lock.json apps/package-lock.json
# drop the three node_modules/@*/ui entries from the copy, then:
(cd apps && npm install --package-lock-only)
```

## Records

- The control plane keeps one SQLite file per application in its data directory:
  `robinauts.db`, `oneberth.db`, `neorc.db`. An application of FA1 keeps a file of its own
  there, named after it.
- `backend.py` gives each application the data directory, which `ROBINAUTS_DATA_DIR` names.
- The data directory is in the volume `control-data`. An application's records stay and go
  with the control plane's.
- Robinauts checks its own file at each start, and pins its schema. `robinauts.db` holds
  Robinauts' tables alone.
- An application makes its file at its first start. The tables and the schema version are one
  transaction, so a start that is cut leaves an empty file.
- An application checks its file at each later start. It refuses a file of another version, and
  a file that holds tables and no version.
- A refusal is an error of the application's own. oneberth ends the start with the
  application's name and its sentence.

## What an application may use

- The interface imports React and `@oneberth/ui`. `tsconfig.json` has Robinauts' own
  TypeScript settings.
- The API imports the standard library, FastAPI and oneberth. The control image holds all
  three.
- A stylesheet is plain CSS over oneberth's tokens. Its class names start with the
  application's name.
- The local user holds every role a person may hold. An application declares one such role.

## Adding one

1. A folder under `apps/`, with `backend.py` and `index.tsx`.
2. A line in each list: `apps/backend.py` and `apps/main.tsx`.
3. The files in `APPS`, in `app/src/containers.rs`. A unit test compares the list with the
   folder.
4. Steps in the journey.

## Tests

- The unit tests compare the files the app writes with `apps/`.
- `tests/apps/run.sh` checks `apps/` outside Docker, against Robinauts at the pinned commit. It
  builds the interface with its type check, as the image's first two stages do. It runs
  `tests/apps/test_reviews.py` in the environment the image's last stage installs.
- `test_reviews.py` makes and checks `reviews.db` on real files, and starts `backend.py` as a
  process. CI runs the script on every pull request.
- The journey finds Reviews on the rail below neorc, opens it, reads its panel, asks its API,
  and finds `reviews.db` in the data directory.

## Open

- The gates of the interface's bundle: licences, size, audit.
- oneberth giving a component the storage and a client to its own backend. `backend.py` then
  loses two lines: the data directory, and `composed_into`.
- Applications the person chooses, in the setup folder.
- Mode 3. The control VM's recipe builds this image.
- One application reading another's records.
