import 'package:atra_mobile/src/data/database.dart';
import 'package:atra_mobile/src/data/oplog.dart';
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('pending operations replay in order and stop at the first failure', () async {
    final db = AppDatabase(NativeDatabase.memory());
    final log = OperationLog(db);
    await log.enqueue('POST', '/v1/t/fac-a/alerts/a1/ack', {'by': 'rn-1'});
    await log.enqueue('POST', '/v1/t/fac-a/alerts/a2/ack', {'by': 'rn-1'});
    await log.enqueue('POST', '/v1/t/fac-a/alerts/a3/ack', {'by': 'rn-1'});

    final sent = <String>[];
    var online = true;
    Future<void> send(String method, String path, Map<String, dynamic>? body) async {
      if (!online) throw Exception('offline');
      sent.add(path);
      if (sent.length == 1) online = false;
    }

    expect(await log.replay(send), 1);
    expect((await log.pending()).length, 2);
    expect((await log.pending()).first.lastError, contains('offline'));
    online = true;
    expect(await log.replay(send), 2);
    expect(sent, [
      '/v1/t/fac-a/alerts/a1/ack',
      '/v1/t/fac-a/alerts/a2/ack',
      '/v1/t/fac-a/alerts/a3/ack',
    ]);
    expect(await log.watchPendingCount().first, 0);
    await db.close();
  });
}
