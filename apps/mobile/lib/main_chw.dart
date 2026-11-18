import 'package:flutter/material.dart';

import 'src/app.dart';
import 'src/config.dart';
import 'src/flavor.dart';

void main() => runApp(AtraApp(config: AppConfig.fromEnvironment(Flavor.chw)));
