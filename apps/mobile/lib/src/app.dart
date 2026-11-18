import 'package:flutter/material.dart';

import '../l10n/generated/app_localizations.dart';
import 'api/apdt_api.dart';
import 'auth/session.dart';
import 'config.dart';
import 'data/database.dart';
import 'data/oplog.dart';
import 'flavor.dart';
import 'ui/dashboard_screen.dart';
import 'ui/fallback_localizations.dart';
import 'ui/login_screen.dart';

class AtraApp extends StatefulWidget {
  const AtraApp({super.key, required this.config, this.api, this.auth, this.database});

  final AppConfig config;
  final ApdtApi? api;
  final AuthService? auth;
  final AppDatabase? database;

  @override
  State<AtraApp> createState() => _AtraAppState();
}

class _AtraAppState extends State<AtraApp> {
  late final ApdtApi _api = widget.api ?? ApdtApi(widget.config.apdtUrl);
  late final AuthService _auth = widget.auth ?? AuthService(_api, widget.config.flavor);
  late final OperationLog _oplog = OperationLog(widget.database ?? AppDatabase());
  Session? _session;

  @override
  void initState() {
    super.initState();
    _auth.restore().then((s) {
      if (mounted && s != null) setState(() => _session = s);
    });
  }

  String _title(AppLocalizations t) => switch (widget.config.flavor) {
    Flavor.person => t.appTitlePerson,
    Flavor.carer => t.appTitleCarer,
    Flavor.patient => t.appTitlePatient,
    Flavor.ward => t.appTitleWard,
    Flavor.chw => t.appTitleChw,
  };

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      onGenerateTitle: (context) => _title(AppLocalizations.of(context)),
      theme: ThemeData(colorSchemeSeed: const Color(0xFF0F6B5C), useMaterial3: true),
      darkTheme: ThemeData(
        colorSchemeSeed: const Color(0xFF0F6B5C),
        brightness: Brightness.dark,
        useMaterial3: true,
      ),
      localizationsDelegates: const [AppLocalizations.delegate, ...fallbackDelegates],
      supportedLocales: AppLocalizations.supportedLocales,
      home: Builder(
        builder: (context) {
          final title = _title(AppLocalizations.of(context));
          final session = _session;
          if (session == null) {
            return LoginScreen(
              auth: _auth,
              title: title,
              onSignedIn: (s) => setState(() => _session = s),
            );
          }
          return DashboardScreen(
            session: session,
            flavor: widget.config.flavor,
            api: _api,
            oplog: _oplog,
            title: title,
            onSignOut: () async {
              await _auth.signOut();
              setState(() => _session = null);
            },
          );
        },
      ),
    );
  }
}
