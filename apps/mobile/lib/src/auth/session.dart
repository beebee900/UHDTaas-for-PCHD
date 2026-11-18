import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../api/apdt_api.dart';
import '../flavor.dart';

/// A signed-in user, read from the access token's claims.
class Session {
  Session({
    required this.token,
    required this.subject,
    required this.role,
    this.tenantId,
    this.hdtId,
  });

  factory Session.fromToken(String token) {
    final parts = token.split('.');
    if (parts.length != 3) throw const FormatException('not a JWT');
    final claims = jsonDecode(
      utf8.decode(base64Url.decode(base64Url.normalize(parts[1]))),
    ) as Map<String, dynamic>;
    return Session(
      token: token,
      subject: claims['sub'] as String,
      role: claims['role'] as String? ?? '',
      tenantId: claims['tenant_id'] as String?,
      hdtId: claims['hdt_id'] as String?,
    );
  }

  final String token;
  final String subject;
  final String role;
  final String? tenantId;
  final String? hdtId;
}

class WrongAppForRole implements Exception {
  WrongAppForRole(this.role);

  final String role;
}

/// Signs in against the APDT (local issuer in p0) and keeps the token in secure storage.
class AuthService {
  AuthService(this.api, this.flavor, {FlutterSecureStorage? storage})
    : _storage = storage ?? const FlutterSecureStorage();

  static const _key = 'atra.token';

  final ApdtApi api;
  final Flavor flavor;
  final FlutterSecureStorage _storage;

  Future<Session> signIn(String username, String password) async {
    final reply =
        await api.login(body: {'username': username, 'password': password}) as Map<String, dynamic>;
    final session = Session.fromToken(reply['access_token'] as String);
    if (!flavor.roles.contains(session.role)) {
      throw WrongAppForRole(session.role);
    }
    await _storage.write(key: _key, value: session.token);
    api.token = session.token;
    return session;
  }

  Future<Session?> restore() async {
    final token = await _storage.read(key: _key);
    if (token == null) return null;
    try {
      final session = Session.fromToken(token);
      api.token = token;
      return session;
    } on FormatException {
      await _storage.delete(key: _key);
      return null;
    }
  }

  Future<void> signOut() async {
    api.token = null;
    await _storage.delete(key: _key);
  }
}
