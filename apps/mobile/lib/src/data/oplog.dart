import 'dart:convert';

import 'package:drift/drift.dart';

import 'database.dart';

typedef SendFn = Future<void> Function(String method, String path, Map<String, dynamic>? body);

/// Offline operation log: queue writes, replay them in order, keep failures for review.
class OperationLog {
  OperationLog(this.db);

  final AppDatabase db;

  Future<int> enqueue(String method, String path, [Map<String, dynamic>? body]) => db
      .into(db.opLog)
      .insert(
        OpLogCompanion.insert(
          method: method,
          path: path,
          body: Value(body == null ? null : jsonEncode(body)),
        ),
      );

  Future<List<OpLogData>> pending() =>
      (db.select(db.opLog)
            ..where((t) => t.status.equals('pending'))
            ..orderBy([(t) => OrderingTerm.asc(t.id)]))
          .get();

  Stream<int> watchPendingCount() {
    final count = db.opLog.id.count();
    final query = db.selectOnly(db.opLog)
      ..addColumns([count])
      ..where(db.opLog.status.equals('pending'));
    return query.map((row) => row.read(count) ?? 0).watchSingle();
  }

  /// Sends pending operations in order. Stops at the first network failure so order holds.
  Future<int> replay(SendFn send) async {
    var sent = 0;
    for (final op in await pending()) {
      try {
        await send(
          op.method,
          op.path,
          op.body == null ? null : jsonDecode(op.body!) as Map<String, dynamic>,
        );
      } on Exception catch (error) {
        await (db.update(db.opLog)..where((t) => t.id.equals(op.id))).write(
          OpLogCompanion(lastError: Value(error.toString())),
        );
        break;
      }
      await (db.update(
        db.opLog,
      )..where((t) => t.id.equals(op.id))).write(const OpLogCompanion(status: Value('sent')));
      sent++;
    }
    return sent;
  }
}
