// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'database.dart';

// ignore_for_file: type=lint
class $OpLogTable extends OpLog with TableInfo<$OpLogTable, OpLogData> {
  @override
  final GeneratedDatabase attachedDatabase;
  final String? _alias;
  $OpLogTable(this.attachedDatabase, [this._alias]);
  static const VerificationMeta _idMeta = const VerificationMeta('id');
  @override
  late final GeneratedColumn<int> id = GeneratedColumn<int>(
    'id',
    aliasedName,
    false,
    hasAutoIncrement: true,
    type: DriftSqlType.int,
    requiredDuringInsert: false,
    defaultConstraints: GeneratedColumn.constraintIsAlways('PRIMARY KEY AUTOINCREMENT'),
  );
  static const VerificationMeta _methodMeta = const VerificationMeta('method');
  @override
  late final GeneratedColumn<String> method = GeneratedColumn<String>(
    'method',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _pathMeta = const VerificationMeta('path');
  @override
  late final GeneratedColumn<String> path = GeneratedColumn<String>(
    'path',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _bodyMeta = const VerificationMeta('body');
  @override
  late final GeneratedColumn<String> body = GeneratedColumn<String>(
    'body',
    aliasedName,
    true,
    type: DriftSqlType.string,
    requiredDuringInsert: false,
  );
  static const VerificationMeta _createdAtMeta = const VerificationMeta('createdAt');
  @override
  late final GeneratedColumn<DateTime> createdAt = GeneratedColumn<DateTime>(
    'created_at',
    aliasedName,
    false,
    type: DriftSqlType.dateTime,
    requiredDuringInsert: false,
    defaultValue: currentDateAndTime,
  );
  static const VerificationMeta _statusMeta = const VerificationMeta('status');
  @override
  late final GeneratedColumn<String> status = GeneratedColumn<String>(
    'status',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: false,
    defaultValue: const Constant('pending'),
  );
  static const VerificationMeta _lastErrorMeta = const VerificationMeta('lastError');
  @override
  late final GeneratedColumn<String> lastError = GeneratedColumn<String>(
    'last_error',
    aliasedName,
    true,
    type: DriftSqlType.string,
    requiredDuringInsert: false,
  );
  @override
  List<GeneratedColumn> get $columns => [id, method, path, body, createdAt, status, lastError];
  @override
  String get aliasedName => _alias ?? actualTableName;
  @override
  String get actualTableName => $name;
  static const String $name = 'op_log';
  @override
  VerificationContext validateIntegrity(
    Insertable<OpLogData> instance, {
    bool isInserting = false,
  }) {
    final context = VerificationContext();
    final data = instance.toColumns(true);
    if (data.containsKey('id')) {
      context.handle(_idMeta, id.isAcceptableOrUnknown(data['id']!, _idMeta));
    }
    if (data.containsKey('method')) {
      context.handle(_methodMeta, method.isAcceptableOrUnknown(data['method']!, _methodMeta));
    } else if (isInserting) {
      context.missing(_methodMeta);
    }
    if (data.containsKey('path')) {
      context.handle(_pathMeta, path.isAcceptableOrUnknown(data['path']!, _pathMeta));
    } else if (isInserting) {
      context.missing(_pathMeta);
    }
    if (data.containsKey('body')) {
      context.handle(_bodyMeta, body.isAcceptableOrUnknown(data['body']!, _bodyMeta));
    }
    if (data.containsKey('created_at')) {
      context.handle(
        _createdAtMeta,
        createdAt.isAcceptableOrUnknown(data['created_at']!, _createdAtMeta),
      );
    }
    if (data.containsKey('status')) {
      context.handle(_statusMeta, status.isAcceptableOrUnknown(data['status']!, _statusMeta));
    }
    if (data.containsKey('last_error')) {
      context.handle(
        _lastErrorMeta,
        lastError.isAcceptableOrUnknown(data['last_error']!, _lastErrorMeta),
      );
    }
    return context;
  }

  @override
  Set<GeneratedColumn> get $primaryKey => {id};
  @override
  OpLogData map(Map<String, dynamic> data, {String? tablePrefix}) {
    final effectivePrefix = tablePrefix != null ? '$tablePrefix.' : '';
    return OpLogData(
      id: attachedDatabase.typeMapping.read(DriftSqlType.int, data['${effectivePrefix}id'])!,
      method: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}method'],
      )!,
      path: attachedDatabase.typeMapping.read(DriftSqlType.string, data['${effectivePrefix}path'])!,
      body: attachedDatabase.typeMapping.read(DriftSqlType.string, data['${effectivePrefix}body']),
      createdAt: attachedDatabase.typeMapping.read(
        DriftSqlType.dateTime,
        data['${effectivePrefix}created_at'],
      )!,
      status: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}status'],
      )!,
      lastError: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}last_error'],
      ),
    );
  }

  @override
  $OpLogTable createAlias(String alias) {
    return $OpLogTable(attachedDatabase, alias);
  }
}

class OpLogData extends DataClass implements Insertable<OpLogData> {
  final int id;
  final String method;
  final String path;
  final String? body;
  final DateTime createdAt;
  final String status;
  final String? lastError;
  const OpLogData({
    required this.id,
    required this.method,
    required this.path,
    this.body,
    required this.createdAt,
    required this.status,
    this.lastError,
  });
  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    map['id'] = Variable<int>(id);
    map['method'] = Variable<String>(method);
    map['path'] = Variable<String>(path);
    if (!nullToAbsent || body != null) {
      map['body'] = Variable<String>(body);
    }
    map['created_at'] = Variable<DateTime>(createdAt);
    map['status'] = Variable<String>(status);
    if (!nullToAbsent || lastError != null) {
      map['last_error'] = Variable<String>(lastError);
    }
    return map;
  }

  OpLogCompanion toCompanion(bool nullToAbsent) {
    return OpLogCompanion(
      id: Value(id),
      method: Value(method),
      path: Value(path),
      body: body == null && nullToAbsent ? const Value.absent() : Value(body),
      createdAt: Value(createdAt),
      status: Value(status),
      lastError: lastError == null && nullToAbsent ? const Value.absent() : Value(lastError),
    );
  }

  factory OpLogData.fromJson(Map<String, dynamic> json, {ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return OpLogData(
      id: serializer.fromJson<int>(json['id']),
      method: serializer.fromJson<String>(json['method']),
      path: serializer.fromJson<String>(json['path']),
      body: serializer.fromJson<String?>(json['body']),
      createdAt: serializer.fromJson<DateTime>(json['createdAt']),
      status: serializer.fromJson<String>(json['status']),
      lastError: serializer.fromJson<String?>(json['lastError']),
    );
  }
  @override
  Map<String, dynamic> toJson({ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return <String, dynamic>{
      'id': serializer.toJson<int>(id),
      'method': serializer.toJson<String>(method),
      'path': serializer.toJson<String>(path),
      'body': serializer.toJson<String?>(body),
      'createdAt': serializer.toJson<DateTime>(createdAt),
      'status': serializer.toJson<String>(status),
      'lastError': serializer.toJson<String?>(lastError),
    };
  }

  OpLogData copyWith({
    int? id,
    String? method,
    String? path,
    Value<String?> body = const Value.absent(),
    DateTime? createdAt,
    String? status,
    Value<String?> lastError = const Value.absent(),
  }) => OpLogData(
    id: id ?? this.id,
    method: method ?? this.method,
    path: path ?? this.path,
    body: body.present ? body.value : this.body,
    createdAt: createdAt ?? this.createdAt,
    status: status ?? this.status,
    lastError: lastError.present ? lastError.value : this.lastError,
  );
  OpLogData copyWithCompanion(OpLogCompanion data) {
    return OpLogData(
      id: data.id.present ? data.id.value : this.id,
      method: data.method.present ? data.method.value : this.method,
      path: data.path.present ? data.path.value : this.path,
      body: data.body.present ? data.body.value : this.body,
      createdAt: data.createdAt.present ? data.createdAt.value : this.createdAt,
      status: data.status.present ? data.status.value : this.status,
      lastError: data.lastError.present ? data.lastError.value : this.lastError,
    );
  }

  @override
  String toString() {
    return (StringBuffer('OpLogData(')
          ..write('id: $id, ')
          ..write('method: $method, ')
          ..write('path: $path, ')
          ..write('body: $body, ')
          ..write('createdAt: $createdAt, ')
          ..write('status: $status, ')
          ..write('lastError: $lastError')
          ..write(')'))
        .toString();
  }

  @override
  int get hashCode => Object.hash(id, method, path, body, createdAt, status, lastError);
  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      (other is OpLogData &&
          other.id == this.id &&
          other.method == this.method &&
          other.path == this.path &&
          other.body == this.body &&
          other.createdAt == this.createdAt &&
          other.status == this.status &&
          other.lastError == this.lastError);
}

class OpLogCompanion extends UpdateCompanion<OpLogData> {
  final Value<int> id;
  final Value<String> method;
  final Value<String> path;
  final Value<String?> body;
  final Value<DateTime> createdAt;
  final Value<String> status;
  final Value<String?> lastError;
  const OpLogCompanion({
    this.id = const Value.absent(),
    this.method = const Value.absent(),
    this.path = const Value.absent(),
    this.body = const Value.absent(),
    this.createdAt = const Value.absent(),
    this.status = const Value.absent(),
    this.lastError = const Value.absent(),
  });
  OpLogCompanion.insert({
    this.id = const Value.absent(),
    required String method,
    required String path,
    this.body = const Value.absent(),
    this.createdAt = const Value.absent(),
    this.status = const Value.absent(),
    this.lastError = const Value.absent(),
  }) : method = Value(method),
       path = Value(path);
  static Insertable<OpLogData> custom({
    Expression<int>? id,
    Expression<String>? method,
    Expression<String>? path,
    Expression<String>? body,
    Expression<DateTime>? createdAt,
    Expression<String>? status,
    Expression<String>? lastError,
  }) {
    return RawValuesInsertable({
      if (id != null) 'id': id,
      if (method != null) 'method': method,
      if (path != null) 'path': path,
      if (body != null) 'body': body,
      if (createdAt != null) 'created_at': createdAt,
      if (status != null) 'status': status,
      if (lastError != null) 'last_error': lastError,
    });
  }

  OpLogCompanion copyWith({
    Value<int>? id,
    Value<String>? method,
    Value<String>? path,
    Value<String?>? body,
    Value<DateTime>? createdAt,
    Value<String>? status,
    Value<String?>? lastError,
  }) {
    return OpLogCompanion(
      id: id ?? this.id,
      method: method ?? this.method,
      path: path ?? this.path,
      body: body ?? this.body,
      createdAt: createdAt ?? this.createdAt,
      status: status ?? this.status,
      lastError: lastError ?? this.lastError,
    );
  }

  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    if (id.present) {
      map['id'] = Variable<int>(id.value);
    }
    if (method.present) {
      map['method'] = Variable<String>(method.value);
    }
    if (path.present) {
      map['path'] = Variable<String>(path.value);
    }
    if (body.present) {
      map['body'] = Variable<String>(body.value);
    }
    if (createdAt.present) {
      map['created_at'] = Variable<DateTime>(createdAt.value);
    }
    if (status.present) {
      map['status'] = Variable<String>(status.value);
    }
    if (lastError.present) {
      map['last_error'] = Variable<String>(lastError.value);
    }
    return map;
  }

  @override
  String toString() {
    return (StringBuffer('OpLogCompanion(')
          ..write('id: $id, ')
          ..write('method: $method, ')
          ..write('path: $path, ')
          ..write('body: $body, ')
          ..write('createdAt: $createdAt, ')
          ..write('status: $status, ')
          ..write('lastError: $lastError')
          ..write(')'))
        .toString();
  }
}

abstract class _$AppDatabase extends GeneratedDatabase {
  _$AppDatabase(QueryExecutor e) : super(e);
  $AppDatabaseManager get managers => $AppDatabaseManager(this);
  late final $OpLogTable opLog = $OpLogTable(this);
  @override
  Iterable<TableInfo<Table, Object?>> get allTables =>
      allSchemaEntities.whereType<TableInfo<Table, Object?>>();
  @override
  List<DatabaseSchemaEntity> get allSchemaEntities => [opLog];
}

typedef $$OpLogTableCreateCompanionBuilder = OpLogCompanion Function({
  Value<int> id,
  required String method,
  required String path,
  Value<String?> body,
  Value<DateTime> createdAt,
  Value<String> status,
  Value<String?> lastError,
});
typedef $$OpLogTableUpdateCompanionBuilder = OpLogCompanion Function({
  Value<int> id,
  Value<String> method,
  Value<String> path,
  Value<String?> body,
  Value<DateTime> createdAt,
  Value<String> status,
  Value<String?> lastError,
});

class $$OpLogTableFilterComposer extends Composer<_$AppDatabase, $OpLogTable> {
  $$OpLogTableFilterComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnFilters<int> get id =>
      $composableBuilder(column: $table.id, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get method =>
      $composableBuilder(column: $table.method, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get path =>
      $composableBuilder(column: $table.path, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get body =>
      $composableBuilder(column: $table.body, builder: (column) => ColumnFilters(column));

  ColumnFilters<DateTime> get createdAt =>
      $composableBuilder(column: $table.createdAt, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get status =>
      $composableBuilder(column: $table.status, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get lastError =>
      $composableBuilder(column: $table.lastError, builder: (column) => ColumnFilters(column));
}

class $$OpLogTableOrderingComposer extends Composer<_$AppDatabase, $OpLogTable> {
  $$OpLogTableOrderingComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnOrderings<int> get id =>
      $composableBuilder(column: $table.id, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get method =>
      $composableBuilder(column: $table.method, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get path =>
      $composableBuilder(column: $table.path, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get body =>
      $composableBuilder(column: $table.body, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<DateTime> get createdAt =>
      $composableBuilder(column: $table.createdAt, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get status =>
      $composableBuilder(column: $table.status, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get lastError =>
      $composableBuilder(column: $table.lastError, builder: (column) => ColumnOrderings(column));
}

class $$OpLogTableAnnotationComposer extends Composer<_$AppDatabase, $OpLogTable> {
  $$OpLogTableAnnotationComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  GeneratedColumn<int> get id => $composableBuilder(column: $table.id, builder: (column) => column);

  GeneratedColumn<String> get method =>
      $composableBuilder(column: $table.method, builder: (column) => column);

  GeneratedColumn<String> get path =>
      $composableBuilder(column: $table.path, builder: (column) => column);

  GeneratedColumn<String> get body =>
      $composableBuilder(column: $table.body, builder: (column) => column);

  GeneratedColumn<DateTime> get createdAt =>
      $composableBuilder(column: $table.createdAt, builder: (column) => column);

  GeneratedColumn<String> get status =>
      $composableBuilder(column: $table.status, builder: (column) => column);

  GeneratedColumn<String> get lastError =>
      $composableBuilder(column: $table.lastError, builder: (column) => column);
}

class $$OpLogTableTableManager
    extends
        RootTableManager<
          _$AppDatabase,
          $OpLogTable,
          OpLogData,
          $$OpLogTableFilterComposer,
          $$OpLogTableOrderingComposer,
          $$OpLogTableAnnotationComposer,
          $$OpLogTableCreateCompanionBuilder,
          $$OpLogTableUpdateCompanionBuilder,
          (OpLogData, BaseReferences<_$AppDatabase, $OpLogTable, OpLogData>),
          OpLogData,
          PrefetchHooks Function()
        > {
  $$OpLogTableTableManager(_$AppDatabase db, $OpLogTable table)
    : super(
        TableManagerState(
          db: db,
          table: table,
          createFilteringComposer: () => $$OpLogTableFilterComposer($db: db, $table: table),
          createOrderingComposer: () => $$OpLogTableOrderingComposer($db: db, $table: table),
          createComputedFieldComposer: () => $$OpLogTableAnnotationComposer($db: db, $table: table),
          updateCompanionCallback:
              ({
                Value<int> id = const Value.absent(),
                Value<String> method = const Value.absent(),
                Value<String> path = const Value.absent(),
                Value<String?> body = const Value.absent(),
                Value<DateTime> createdAt = const Value.absent(),
                Value<String> status = const Value.absent(),
                Value<String?> lastError = const Value.absent(),
              }) => OpLogCompanion(
                id: id,
                method: method,
                path: path,
                body: body,
                createdAt: createdAt,
                status: status,
                lastError: lastError,
              ),
          createCompanionCallback:
              ({
                Value<int> id = const Value.absent(),
                required String method,
                required String path,
                Value<String?> body = const Value.absent(),
                Value<DateTime> createdAt = const Value.absent(),
                Value<String> status = const Value.absent(),
                Value<String?> lastError = const Value.absent(),
              }) => OpLogCompanion.insert(
                id: id,
                method: method,
                path: path,
                body: body,
                createdAt: createdAt,
                status: status,
                lastError: lastError,
              ),
          withReferenceMapper: (p0) => p0
              .map(
                (e) => (
                  e.readTable<$OpLogTable, OpLogData>(table),
                  BaseReferences<_$AppDatabase, $OpLogTable, OpLogData>(db, table, e),
                ),
              )
              .toList(),
          prefetchHooksCallback: null,
        ),
      );
}

typedef $$OpLogTableProcessedTableManager =
    ProcessedTableManager<
      _$AppDatabase,
      $OpLogTable,
      OpLogData,
      $$OpLogTableFilterComposer,
      $$OpLogTableOrderingComposer,
      $$OpLogTableAnnotationComposer,
      $$OpLogTableCreateCompanionBuilder,
      $$OpLogTableUpdateCompanionBuilder,
      (OpLogData, BaseReferences<_$AppDatabase, $OpLogTable, OpLogData>),
      OpLogData,
      PrefetchHooks Function()
    >;

class $AppDatabaseManager {
  final _$AppDatabase _db;
  $AppDatabaseManager(this._db);
  $$OpLogTableTableManager get opLog => $$OpLogTableTableManager(_db, _db.opLog);
}
