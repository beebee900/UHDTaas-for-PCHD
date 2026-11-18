import 'package:flutter/material.dart';

import 'src/app.dart';
import 'src/config.dart';

/// Default entry point; the flavour comes from `--dart-define=FLAVOR=...`.
void main() => runApp(AtraApp(config: AppConfig.fromEnvironment()));
