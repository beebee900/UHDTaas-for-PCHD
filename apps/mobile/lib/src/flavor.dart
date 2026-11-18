/// The five mobile apps built from this code base (design 02, 2.1).
enum Flavor {
  person,
  carer,
  patient,
  ward,
  chw;

  static Flavor parse(String name) =>
      Flavor.values.firstWhere((f) => f.name == name, orElse: () => Flavor.person);

  /// Roles that may sign in to this app.
  Set<String> get roles => switch (this) {
    Flavor.person => {'person'},
    Flavor.carer => {'carer'},
    Flavor.patient => {'patient', 'proxy'},
    Flavor.ward => {'nurse', 'medical_officer'},
    Flavor.chw => {'community_health_worker'},
  };

  bool get clinical => this == Flavor.ward || this == Flavor.chw;
}
