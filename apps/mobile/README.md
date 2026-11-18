# ATRA mobile apps

One Flutter code base for five apps: `person`, `carer`, `patient`, `ward` and `chw`.

- Run a flavour: `flutter run -t lib/main_ward.dart --flavor ward`
- Web build: `flutter build web -t lib/main_ward.dart --no-web-resources-cdn`
- API address: `--dart-define=APDT_URL=http://127.0.0.1:8200`

`lib/src/api/apdt_api.dart` is generated from `contracts/openapi/apdt.yaml` by `tool/gen_api.py`.
Translations live in `lib/l10n/*.arb`; text a locale does not translate yet is shown in English.
Writes made offline wait in the operation log (`lib/src/data/`) and are sent in order later.
