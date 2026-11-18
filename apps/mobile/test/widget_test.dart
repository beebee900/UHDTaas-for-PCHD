import 'dart:convert';

import 'package:atra_mobile/src/api/apdt_api.dart';
import 'package:atra_mobile/src/app.dart';
import 'package:atra_mobile/src/auth/session.dart';
import 'package:atra_mobile/src/config.dart';
import 'package:atra_mobile/src/data/database.dart';
import 'package:atra_mobile/src/flavor.dart';
import 'package:drift/native.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

String token(String role, String tenant) {
  String part(Map<String, dynamic> m) =>
      base64Url.encode(utf8.encode(jsonEncode(m))).replaceAll('=', '');
  final exp = DateTime.now().add(const Duration(hours: 1)).millisecondsSinceEpoch ~/ 1000;
  return '${part({'alg': 'RS256'})}.${part({'sub': 'nurse.$tenant', 'role': role, 'tenant_id': tenant, 'exp': exp})}.sig';
}

MockClient apdtStub() => MockClient((request) async {
  if (request.url.path == '/auth/token') {
    final body = jsonDecode(request.body) as Map<String, dynamic>;
    if (body['password'] != 'right') {
      return http.Response(jsonEncode({'status': 401, 'detail': 'unknown user'}), 401);
    }
    return http.Response(
      jsonEncode({'access_token': token('nurse', 'fac-a'), 'expires_in': 3600, 'role': 'nurse'}),
      200,
    );
  }
  if (request.url.path == '/v1/t/fac-a/worklists/nurse') {
    expect(request.headers['authorization'], startsWith('Bearer '));
    return http.Response(
      jsonEncode({
        'role': 'nurse',
        'tenant_id': 'fac-a',
        'items': [
          {'item_id': 'wl-ao', 'kind': 'review', 'title': 'Review A.O.', 'priority': 3},
        ],
      }),
      200,
    );
  }
  return http.Response('{}', 404);
});

Widget app(Flavor flavor, AppDatabase db) {
  final api = ApdtApi('http://apdt.test', client: apdtStub());
  return AtraApp(
    config: AppConfig(flavor: flavor, apdtUrl: 'http://apdt.test'),
    api: api,
    auth: AuthService(api, flavor),
    database: db,
  );
}

void main() {
  late AppDatabase db;

  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
    db = AppDatabase(NativeDatabase.memory());
  });

  // Drift keeps a timer for stream queries until the widgets and the database are closed.
  tearDown(() => db.close());

  Future<void> finish(WidgetTester tester) async {
    await tester.pumpWidget(const SizedBox());
    await tester.pump(const Duration(seconds: 1));
  }

  testWidgets('a nurse signs in to the ward app and sees the worklist', (tester) async {
    await tester.pumpWidget(app(Flavor.ward, db));
    await tester.pumpAndSettle();
    expect(find.text('Sign in'), findsWidgets);
    await tester.enterText(find.byKey(const Key('username')), 'nurse.fac-a');
    await tester.enterText(find.byKey(const Key('password')), 'right');
    await tester.tap(find.byKey(const Key('submit')));
    await tester.pumpAndSettle();
    expect(find.text('Dashboard'), findsOneWidget);
    expect(find.text('Review A.O.'), findsOneWidget);
    expect(find.text('All changes are sent.'), findsOneWidget);
    await finish(tester);
  });

  testWidgets('a wrong password shows an error', (tester) async {
    await tester.pumpWidget(app(Flavor.ward, db));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('username')), 'nurse.fac-a');
    await tester.enterText(find.byKey(const Key('password')), 'wrong');
    await tester.tap(find.byKey(const Key('submit')));
    await tester.pumpAndSettle();
    expect(find.text('The username or password is not correct.'), findsOneWidget);
  });

  testWidgets('a nurse cannot use the person app', (tester) async {
    await tester.pumpWidget(app(Flavor.person, db));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('username')), 'nurse.fac-a');
    await tester.enterText(find.byKey(const Key('password')), 'right');
    await tester.tap(find.byKey(const Key('submit')));
    await tester.pumpAndSettle();
    expect(find.text('Dashboard'), findsNothing);
  });

  testWidgets('every app locale renders, untranslated text in English', (tester) async {
    for (final locale in const [Locale('yo'), Locale('ha'), Locale('ig'), Locale('pcm')]) {
      tester.platformDispatcher.localeTestValue = locale;
      await tester.pumpWidget(app(Flavor.patient, db));
      await tester.pumpAndSettle();
      expect(find.text('Sign in'), findsWidgets);
    }
    tester.platformDispatcher.clearLocaleTestValue();
  });
}
