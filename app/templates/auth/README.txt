Authentication templates live here.

Current expected contents:
- login template

Auth remains simple:
- admin and player users share the same login form
- authorization differences are enforced in routes/decorators, not by separate auth templates
