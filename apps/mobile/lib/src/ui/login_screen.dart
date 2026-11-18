import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import '../../l10n/generated/app_localizations.dart';
import '../api/apdt_api.dart';
import '../auth/session.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key, required this.auth, required this.onSignedIn, required this.title});

  final AuthService auth;
  final ValueChanged<Session> onSignedIn;
  final String title;

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _username = TextEditingController();
  final _password = TextEditingController();
  String? _error;
  bool _busy = false;

  @override
  void dispose() {
    _username.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final t = AppLocalizations.of(context);
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      widget.onSignedIn(await widget.auth.signIn(_username.text.trim(), _password.text));
    } on ApiException {
      setState(() => _error = t.signInFailed);
    } on WrongAppForRole {
      setState(() => _error = t.signInFailed);
    } on http.ClientException {
      setState(() => _error = t.serviceUnreachable);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(widget.title)),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 420),
          child: ListView(
            padding: const EdgeInsets.all(16),
            shrinkWrap: true,
            children: [
              Text(t.signIn, style: Theme.of(context).textTheme.headlineSmall),
              const SizedBox(height: 16),
              TextField(
                key: const Key('username'),
                controller: _username,
                decoration: InputDecoration(labelText: t.username),
                autofillHints: const [AutofillHints.username],
              ),
              const SizedBox(height: 12),
              TextField(
                key: const Key('password'),
                controller: _password,
                obscureText: true,
                decoration: InputDecoration(labelText: t.password),
                autofillHints: const [AutofillHints.password],
                onSubmitted: (_) => _submit(),
              ),
              if (_error != null) ...[
                const SizedBox(height: 12),
                Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
              ],
              const SizedBox(height: 16),
              FilledButton(
                key: const Key('submit'),
                onPressed: _busy ? null : _submit,
                child: Text(t.signIn),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
