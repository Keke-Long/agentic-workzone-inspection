# Frozen manual sources

The current formal normative corpus is **MUTCD 11th Edition (December 2023)**.
It is indexed before any test-scene query by `build_mutcd_structure_v1.py`.

| File | SHA-256 | Role |
|---|---|---|
| `MUTCD_11th_Edition_2023_Hotlinks.pdf` | `5221404db3c27ec302d04d202c0e4b3b297857acebe94c632933f91c210ff835` | Sole formal normative retrieval corpus |
| `AASHTO_Maintenance_Manual_for_Roadways.pdf` | `5f931cbb4b31aa440be53b167bfd0022ec2f53fde30a8b40a636054303018fbe` | Frozen provenance copy only; excluded from formal retrieval and scoring |

The AASHTO manual is not mixed into the formal corpus because doing so would
create an unrequested second authority and make source attribution ambiguous.
Its role can be changed only through an explicit protocol revision.

