import 'flavor.dart';

/// Build-time settings: `--dart-define=APDT_URL=...` and `--dart-define=FLAVOR=...`.
class AppConfig {
  const AppConfig({required this.flavor, required this.apdtUrl});

  factory AppConfig.fromEnvironment([Flavor? flavor]) => AppConfig(
    flavor: flavor ?? Flavor.parse(const String.fromEnvironment('FLAVOR', defaultValue: 'person')),
    apdtUrl: const String.fromEnvironment('APDT_URL', defaultValue: 'http://127.0.0.1:8200'),
  );

  final Flavor flavor;
  final String apdtUrl;
}
