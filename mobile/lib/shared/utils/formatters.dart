import 'package:intl/intl.dart';

/// Display formatting shared by both role apps.
class Formatters {
  const Formatters._();

  static const Map<String, String> _currencyWord = <String, String>{
    'uz': "so'm",
    'ru': 'сум',
    'en': 'UZS',
  };

  /// `50 000 so'm` — Uzbek sum uses a space as the thousands separator.
  static String money(int amountUzs, String locale) {
    final String digits =
        NumberFormat('#,###', 'en_US').format(amountUzs).replaceAll(',', ' ');
    return '$digits ${_currencyWord[locale] ?? "so'm"}';
  }

  static String date(DateTime value, String locale) =>
      DateFormat('dd.MM.yyyy').format(value.toLocal());

  static String time(DateTime value) => DateFormat('HH:mm').format(value.toLocal());

  static String dateTime(DateTime value, String locale) =>
      '${date(value, locale)}, ${time(value)}';

  static String monthDay(DateTime value) => DateFormat('dd MMM').format(value.toLocal());

  /// "3 soat oldin" / "2 kun oldin" — relative time for activity lines.
  static String relative(DateTime? value, String locale) {
    if (value == null) {
      return switch (locale) {
        'ru' => 'нет активности',
        'en' => 'no activity',
        _ => 'faollik yo\'q',
      };
    }
    final Duration diff = DateTime.now().difference(value.toLocal());

    if (diff.inMinutes < 1) {
      return switch (locale) {
        'ru' => 'только что',
        'en' => 'just now',
        _ => 'hozir',
      };
    }
    if (diff.inHours < 1) {
      final int m = diff.inMinutes;
      return switch (locale) {
        'ru' => '$m мин назад',
        'en' => '${m}m ago',
        _ => '$m daqiqa oldin',
      };
    }
    if (diff.inHours < 24) {
      final int h = diff.inHours;
      return switch (locale) {
        'ru' => '$h ч назад',
        'en' => '${h}h ago',
        _ => '$h soat oldin',
      };
    }
    if (diff.inDays < 30) {
      final int d = diff.inDays;
      return switch (locale) {
        'ru' => '$d дн назад',
        'en' => '${d}d ago',
        _ => '$d kun oldin',
      };
    }
    return date(value, locale);
  }

  /// Countdown to the consultation SLA deadline.
  static String remaining(DateTime? deadline, String locale) {
    if (deadline == null) return '';
    final Duration left = deadline.toLocal().difference(DateTime.now());
    if (left.isNegative) {
      return switch (locale) {
        'ru' => 'срок истёк',
        'en' => 'expired',
        _ => 'muddati tugadi',
      };
    }
    final int hours = left.inHours;
    final int minutes = left.inMinutes % 60;
    if (hours > 0) return '$hours s $minutes d';
    return '$minutes d';
  }

  /// Trims a metric to the precision its series declares.
  static String metric(double value, int decimals) => value.toStringAsFixed(decimals);

  /// Blood pressure and other paired values.
  static String pair(double value, double? secondary, int decimals) {
    if (secondary == null) return metric(value, decimals);
    return '${metric(value, decimals)}/${metric(secondary, decimals)}';
  }

  static String phone(String e164) {
    if (e164.length < 13) return e164;
    // +998901234567 -> +998 90 123 45 67
    return '${e164.substring(0, 4)} ${e164.substring(4, 6)} '
        '${e164.substring(6, 9)} ${e164.substring(9, 11)} '
        '${e164.substring(11)}';
  }

  static String initials(String? name) {
    if (name == null || name.trim().isEmpty) return '?';
    final List<String> parts = name.trim().split(RegExp(r'\s+'));
    if (parts.length == 1) return parts.first.substring(0, 1).toUpperCase();
    return (parts[0].substring(0, 1) + parts[1].substring(0, 1)).toUpperCase();
  }

  static String fileSize(int bytes) {
    if (bytes < 1024) return '$bytes B';
    if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(0)} KB';
    return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
  }
}

/// Input validation for the forms.
class Validators {
  const Validators._();

  static String? required(String? value, String message) {
    if (value == null || value.trim().isEmpty) return message;
    return null;
  }

  static String? phone(String? value, String message) {
    if (value == null || value.trim().isEmpty) return message;
    final String digits = value.replaceAll(RegExp(r'\D'), '');
    // Accepts 901234567, 998901234567 and +998901234567.
    if (digits.length < 9 || digits.length > 12) return message;
    return null;
  }

  static String? positiveInt(String? value, String message) {
    if (value == null || value.trim().isEmpty) return message;
    final int? parsed = int.tryParse(value.trim());
    if (parsed == null || parsed < 0) return message;
    return null;
  }

  static String? number(String? value, String message) {
    if (value == null || value.trim().isEmpty) return message;
    if (double.tryParse(value.trim().replaceAll(',', '.')) == null) {
      return message;
    }
    return null;
  }

  static String? minLength(String? value, int length, String message) {
    if (value == null || value.trim().length < length) return message;
    return null;
  }

  /// Normalise a typed number to E.164 before sending it to the API.
  static String normalizePhone(String raw) {
    final String digits = raw.replaceAll(RegExp(r'\D'), '');
    if (digits.startsWith('998')) return '+$digits';
    if (digits.length == 9) return '+998$digits';
    return raw.startsWith('+') ? raw : '+$digits';
  }
}
