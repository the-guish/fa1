# Applications

FA1 adds applications of its own to the control plane. Each one is a sibling of Robinauts and
neorc: an icon on the rail of the App tab, and an API of its own on the control plane.

| application | shows | keeps |
|---|---|---|
| `reviews` | one panel, a placeholder: "something to review" | `reviews.db`: one table, empty |

## The folder

`apps/` in this repository holds the applications, one folder each.

```
apps/
    index.ts                     the applications on the rail, in order
    <name>/
        ui/                      the interface, in TypeScript
            index.tsx            the name, the title, the icon, the loader of the root component
        python/<package>/        the API: a oneberth component, and the records
```

- The app holds these files, and writes them to `compose/apps/` in its folder at each start.
- A start writes that folder anew. A file a release dropped goes too.

## How an application joins the control plane

oneberth takes any number of applications: components in the backend, icons on the rail.
Robinauts names two, itself and neorc, and takes more from a build ([core.md](core.md), "What
FA1 takes from Robinauts").

- **The image.** `control` is built from Robinauts' `Dockerfile`, with `compose/apps/` as the
  build context `extra`. Robinauts' build compiles `index.ts` and each `ui/` into the
  interface. The image holds the whole folder at `/opt/robinauts/extra/`.
- **The rail.** `apps/index.ts` exports the applications in order. The rail shows them below
  Robinauts and neorc.
- **The API.** `ROBINAUTS_COMPONENTS` names each application's component, and `PYTHONPATH` the
  folder of its package ([compose/compose.yaml](../../compose/compose.yaml)). The control plane
  serves a component under `/<name>/`, behind the sign-in of the App tab.
- **The person.** The local user holds every role a person may hold. An application declares
  one such role.

A change to `apps/` is a new image of `control`. The next start builds it and starts `control`
anew.

## Records

- The control plane keeps one SQLite file per application in its data directory:
  `robinauts.db`, `oneberth.db`, `neorc.db`. An application of FA1 keeps a file of its own
  there, named after it.
- Robinauts gives a component the control plane's environment. `ROBINAUTS_DATA_DIR` names the
  data directory there.
- The data directory is in the volume `control-data`. An application's records stay and go
  with the control plane's.
- Robinauts checks its own file at each start, and pins its schema. `robinauts.db` holds
  Robinauts' tables alone.

## What an application may use

- The interface imports React and `@oneberth/ui`. Robinauts' build compiles it with its own
  TypeScript settings and bundle gates.
- The API imports the standard library, FastAPI and oneberth. The control image holds all
  three.
- A stylesheet is plain CSS over oneberth's tokens. Its class names start with the
  application's name.

## Adding one

1. A folder under `apps/`, with `ui/` and `python/`.
2. A line in `apps/index.ts`.
3. The component in `ROBINAUTS_COMPONENTS` and the package's folder in `PYTHONPATH`, in
   `compose/compose.yaml`.
4. The files in `APPS`, in `app/src/containers.rs`. A unit test compares the list with the
   folder.
5. Steps in the journey.

## Tests

- The unit tests compare the files the app writes with `apps/`.
- The journey finds Reviews on the rail below neorc, opens it, reads its panel, asks its API,
  and finds `reviews.db` in the data directory.

## Open

- A check of an application before the image build. A type error in `ui/` stops
  `docker compose build`.
- Applications the person chooses, in the setup folder.
- Mode 3. The control VM's recipe builds Robinauts' image, and takes `apps/` as the same build
  context.
- One application reading another's records.
