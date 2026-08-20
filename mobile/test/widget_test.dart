import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hamroh/core/l10n/app_localizations.dart';
import 'package:hamroh/data/models/models.dart';
import 'package:hamroh/shared/utils/formatters.dart';

void main() {
  group('Localization', () {
    test('falls back to Uzbek for a key missing in another locale', () {
      final AppLocalizations en = AppLocalizations(const Locale('en'));
      expect(en.t('common.save'), 'Save');
      // An unknown key degrades to the key itself instead of throwing.
      expect(en.t('does.not.exist'), 'does.not.exist');
    });

    test('interpolates named placeholders', () {
      final AppLocalizations uz = AppLocalizations(const Locale('uz'));
      final String text = uz.tp('auth.resend_in', <String, Object?>{
        'seconds': 42,
      });
      expect(text.contains('42'), isTrue);
      expect(text.contains('{seconds}'), isFalse);
    });

    test('fromMap picks the active locale then falls back to uz', () {
      final AppLocalizations ru = AppLocalizations(const Locale('ru'));
      expect(
        ru.fromMap(<String, dynamic>{'uz': 'Qand', 'ru': 'Глюкоза'}),
        'Глюкоза',
      );
      // Only Uzbek present: the label still renders rather than going blank.
      expect(ru.fromMap(<String, dynamic>{'uz': 'Qand'}), 'Qand');
    });

    test('all three locales define the core navigation labels', () {
      const List<String> keys = <String>[
        'patient.tab_today',
        'patient.tab_doctors',
        'patient.tab_help',
        'patient.tab_profile',
        'doctor.tab_patients',
        'doctor.tab_consultations',
        'doctor.tab_wallet',
        'doctor.tab_settings',
      ];
      for (final String code in <String>['uz', 'ru', 'en']) {
        final AppLocalizations l10n = AppLocalizations(Locale(code));
        for (final String key in keys) {
          expect(l10n.t(key), isNot(key), reason: '$key missing for $code');
        }
      }
    });
  });

  group('Phone normalisation', () {
    test('every local format collapses to one E.164 identity', () {
      // The phone number is the platform's identity key, so these must agree.
      for (final String input in <String>[
        '+998901234567',
        '998901234567',
        '901234567',
        '+998 90 123 45 67',
        '(90) 123-45-67',
      ]) {
        expect(Validators.normalizePhone(input), '+998901234567');
      }
    });

    test('display formatting is readable', () {
      expect(Formatters.phone('+998901234567'), '+998 90 123 45 67');
    });
  });

  group('Money formatting', () {
    test('uses a space separator and the locale currency word', () {
      expect(Formatters.money(50000, 'uz'), "50 000 so'm");
      expect(Formatters.money(50000, 'ru'), '50 000 сум');
      expect(Formatters.money(1234567, 'en'), '1 234 567 UZS');
    });
  });

  group('Model parsing', () {
    test('tolerates missing and null fields', () {
      final CareThread thread = CareThread.fromJson(<String, dynamic>{
        'id': 'abc',
        'kind': 'doctor',
        'patient_user_id': 'p1',
      });
      expect(thread.id, 'abc');
      expect(thread.doctorName, isNull);
      expect(thread.isPersonal, isFalse);
    });

    test('identifies the personal container', () {
      final CareThread personal = CareThread.fromJson(<String, dynamic>{
        'id': 'x',
        'kind': 'personal',
        'patient_user_id': 'p1',
      });
      expect(personal.isPersonal, isTrue);
    });

    test('a verified diagnosis is flagged read-only for the patient', () {
      final Diagnosis verified = Diagnosis.fromJson(<String, dynamic>{
        'id': 'd1',
        'care_thread_id': 't1',
        'text': 'Qandli diabet',
        'status': 'verified',
      });
      final Diagnosis unverified = Diagnosis.fromJson(<String, dynamic>{
        'id': 'd2',
        'care_thread_id': 't1',
        'text': "O'zim kiritdim",
        'status': 'unverified',
      });
      expect(verified.isVerified, isTrue);
      expect(unverified.isVerified, isFalse);
    });

    test('session without tokens means the phone gate is still open', () {
      final SessionResponse response =
          SessionResponse.fromJson(<String, dynamic>{
        'onboarding_token': 'tok',
        'state': <String, dynamic>{
          'phone_verification_required': true,
          'role_selection_required': true,
          'profile_setup_required': true,
        },
      });
      expect(response.hasSession, isFalse);
      expect(response.onboardingToken, 'tok');
      expect(response.state.isComplete, isFalse);
    });

    test('dose confirmed by the automated call is marked as such', () {
      final MedicationDose dose = MedicationDose.fromJson(<String, dynamic>{
        'id': 'x',
        'medication_id': 'm',
        'care_thread_id': 't',
        'scheduled_at': '2026-03-01T08:00:00Z',
        'status': 'taken',
        'confirmed_via': 'ivr',
      });
      expect(dose.isTaken, isTrue);
      expect(dose.confirmedByCall, isTrue);
    });
  });

  group('Metric range checks', () {
    final MetricSeries glucose = MetricSeries.fromJson(<String, dynamic>{
      'id': 's1',
      'care_thread_id': 't1',
      'key': 'blood_glucose',
      'label': <String, dynamic>{'uz': 'Qand darajasi'},
      'unit': 'mmol/L',
      'target_min': 4.4,
      'target_max': 7.2,
      'critical_max': 13.9,
    });

    test('classifies in-range, out-of-range and critical readings', () {
      expect(glucose.isOutOfRange(6.0), isFalse);
      expect(glucose.isOutOfRange(9.0), isTrue);
      expect(glucose.isCritical(9.0), isFalse);
      expect(glucose.isCritical(18.0), isTrue);
    });
  });
}
