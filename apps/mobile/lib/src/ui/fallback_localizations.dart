import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

/// Material, Cupertino and widget texts for locales Flutter does not ship (for example
/// Yorùbá or Naijá) come from English, so every app locale renders.
class _Fallback<T> extends LocalizationsDelegate<T> {
  const _Fallback(this.inner);

  final LocalizationsDelegate<T> inner;

  @override
  bool isSupported(Locale locale) => true;

  @override
  Future<T> load(Locale locale) =>
      inner.load(inner.isSupported(locale) ? locale : const Locale('en'));

  @override
  bool shouldReload(covariant LocalizationsDelegate<T> old) => false;
}

const fallbackDelegates = <LocalizationsDelegate<Object>>[
  _Fallback<MaterialLocalizations>(GlobalMaterialLocalizations.delegate),
  _Fallback<CupertinoLocalizations>(GlobalCupertinoLocalizations.delegate),
  _Fallback<WidgetsLocalizations>(GlobalWidgetsLocalizations.delegate),
];
