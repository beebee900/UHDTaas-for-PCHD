import 'package:flutter/material.dart';

import '../../l10n/generated/app_localizations.dart';
import '../api/apdt_api.dart';
import '../auth/session.dart';
import '../data/oplog.dart';
import '../flavor.dart';

class DashboardScreen extends StatelessWidget {
  const DashboardScreen({
    super.key,
    required this.session,
    required this.flavor,
    required this.api,
    required this.oplog,
    required this.title,
    required this.onSignOut,
  });

  final Session session;
  final Flavor flavor;
  final ApdtApi api;
  final OperationLog oplog;
  final String title;
  final VoidCallback onSignOut;

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(
        title: Text(title),
        actions: [TextButton(onPressed: onSignOut, child: Text(t.signOut))],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(t.dashboard, style: Theme.of(context).textTheme.headlineSmall),
          Text(t.signedInAs(session.subject, session.role)),
          const SizedBox(height: 8),
          StreamBuilder<int>(
            stream: oplog.watchPendingCount(),
            builder: (context, snap) => Text(t.pendingChanges(snap.data ?? 0)),
          ),
          if (flavor.clinical && session.tenantId != null) ...[
            const SizedBox(height: 16),
            Text(t.worklist, style: Theme.of(context).textTheme.titleMedium),
            FutureBuilder<dynamic>(
              future: api.getWorklists(tenantId: session.tenantId!, role: session.role),
              builder: (context, snap) {
                if (snap.connectionState != ConnectionState.done) {
                  return const LinearProgressIndicator();
                }
                final items = (snap.data as Map<String, dynamic>?)?['items'] as List<dynamic>?;
                if (items == null || items.isEmpty) {
                  return Text(t.worklistEmpty);
                }
                return Column(
                  children: [
                    for (final item in items.cast<Map<String, dynamic>>())
                      ListTile(
                        title: Text(item['title'] as String),
                        subtitle: Text(item['kind'] as String),
                      ),
                  ],
                );
              },
            ),
          ],
        ],
      ),
    );
  }
}
