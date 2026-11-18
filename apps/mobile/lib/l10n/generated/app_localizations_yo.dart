// ignore: unused_import
import 'package:intl/intl.dart' as intl;

import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for Yoruba (`yo`).
class AppLocalizationsYo extends AppLocalizations {
  AppLocalizationsYo([String locale = 'yo']) : super(locale);

  @override
  String get appTitlePerson => 'My health twin';

  @override
  String get appTitleCarer => 'Carer';

  @override
  String get appTitlePatient => 'My care';

  @override
  String get appTitleWard => 'Ward';

  @override
  String get appTitleChw => 'Community health';

  @override
  String get signIn => 'Sign in';

  @override
  String get username => 'Username';

  @override
  String get password => 'Password';

  @override
  String get signInFailed => 'The username or password is not correct.';

  @override
  String get serviceUnreachable => 'The service cannot be reached. Try again when you are online.';

  @override
  String get signOut => 'Sign out';

  @override
  String get dashboard => 'Dashboard';

  @override
  String signedInAs(String user, String role) {
    return 'Signed in as $user ($role)';
  }

  @override
  String get worklist => 'Worklist';

  @override
  String get worklistEmpty => 'No open items.';

  @override
  String pendingChanges(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count changes wait to be sent.',
      one: '1 change waits to be sent.',
      zero: 'All changes are sent.',
    );
    return '$_temp0';
  }

  @override
  String get language => 'Language';
}
