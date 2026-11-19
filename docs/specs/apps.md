# Applications

FA1 adds applications of its own to the control plane. Each one is a sibling of Robinauts and
neorc: an icon on the rail of the App tab, and an API of its own on the control plane.

| application | shows | keeps |
|---|---|---|
| `reviews` | the changelists to review, and each one's changes side by side ([review-app.md](review-app.md)) | `reviews.db`, and the changelists' commits in `reviews/setup.git` |

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

## The folder

`apps/` in this repository holds the host and the applications, one folder each.

```
apps/
    backend.py                   the backend's list
    main.tsx                     the rail's list
    <name>/
        backend.py               the API: a oneberth component, and the records
        index.tsx                the name, the title, the icon, the loader of the root component
    reviews/
        checks.py                the checks of a setup folder, a program of its own
        tools.py                 the designer's two tools, an MCP server
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
- The review app keeps a git repository beside its file: `reviews/setup.git`, with `main` and
  each changelist's commit.
- The review app reads two paths of the environment. `REVIEWS_WORK` names the designer's
  working copy, and `REVIEWS_PUBLISHED` the bundle of the setup folder's HEAD
  ([review-app.md](review-app.md), "The parts").

## What an application may use

- The interface imports React and `@oneberth/ui`. `tsconfig.json` has Robinauts' own
  TypeScript settings.
- The API imports the standard library, FastAPI and oneberth. The control image holds all
  three.
- A tool server of an application imports the MCP SDK and uvicorn, which Robinauts brings to the
  control image. It listens on the loopback address of `control`, and asks for a key.
- A program an application runs beside itself may import Robinauts and neorc. The review app's
  checks are one: they call the functions Robinauts' start runs.
- The control image holds git, which uv builds neorc and oneberth with. The review app runs it
  on its own repository.
- A stylesheet is plain CSS over oneberth's tokens. Its class names start with the
  application's name.
- The local user holds every role a person may hold. An application declares one such role.
- The app on the host reaches an application with a service token. The launch secret makes it,
  for a role the application declares for it.

## Adding one

1. A folder under `apps/`, with `backend.py` and `index.tsx`.
2. A line in each list: `apps/backend.py` and `apps/main.tsx`.
3. The files in `APPS`, in `app/src/containers.rs`. A unit test compares the list with the
   folder.
4. Steps in the journey.

## Tests

- The unit tests compare the files the app writes with `apps/`.
- `tests/apps/` holds an application's own tests, which run without Docker. The review app's
  run on real git: a setup folder, its bundle, a working copy and the review app's repository.
  `tests/apps/run.sh` runs them in Robinauts' environment, from a checkout at the pinned commit.
- The journey finds Reviews on the rail below neorc. It plays the designer through the three
  tool servers, opens the changelist on the Pending list, reads its change side by side, and
  approves it. A Refresh then takes the change to the setup folder, and Robinauts serves it.

## Open

- A check of the interface before the image build. A type error stops `docker compose build`.
- The gates of the interface's bundle: licences, size, audit.
- oneberth giving a component the storage and a client to its own backend. `backend.py` then
  loses two lines: the data directory, and `composed_into`.
- Applications the person chooses, in the setup folder.
- Mode 3. The control VM's recipe builds this image.
- One application reading another's records.
