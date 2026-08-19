import 'package:flutter/material.dart';

/// Visual system for Hamroh.
///
/// The palette is deliberately calm: this is an app people open while unwell,
/// often several times a day. Colour is reserved for clinical meaning — the
/// risk states and the in/out-of-range bands on trend charts — so it never
/// competes with decoration.
class AppColors {
  const AppColors._();

  static const Color primary = Color(0xFF1F6F5C);
  static const Color primaryDark = Color(0xFF14503F);
  static const Color primaryLight = Color(0xFFE3F1ED);
  static const Color accent = Color(0xFF2F80ED);

  static const Color surface = Color(0xFFFFFFFF);
  static const Color background = Color(0xFFF6F8F7);
  static const Color surfaceAlt = Color(0xFFEFF3F1);

  static const Color textPrimary = Color(0xFF141C1A);
  static const Color textSecondary = Color(0xFF5B6B67);
  static const Color textTertiary = Color(0xFF8A9A95);
  static const Color divider = Color(0xFFE0E7E4);

  /// Clinical status colours, used for risk badges and chart bands.
  static const Color ok = Color(0xFF2E9E6B);
  static const Color warning = Color(0xFFE0A32E);
  static const Color danger = Color(0xFFD9534F);
  static const Color info = Color(0xFF3B7DD8);

  static const Color okSoft = Color(0xFFE6F5EE);
  static const Color warningSoft = Color(0xFFFDF3E0);
  static const Color dangerSoft = Color(0xFFFCEBEA);

  // Dark theme
  static const Color darkBackground = Color(0xFF101614);
  static const Color darkSurface = Color(0xFF19211E);
  static const Color darkSurfaceAlt = Color(0xFF222C29);
  static const Color darkTextPrimary = Color(0xFFEAF0EE);
  static const Color darkTextSecondary = Color(0xFFA9B8B3);
  static const Color darkDivider = Color(0xFF2C3835);

  /// Colour for a risk level as returned by the API (`green|amber|red`).
  static Color forRisk(String level) => switch (level) {
        'red' => danger,
        'amber' => warning,
        _ => ok,
      };

  static Color softForRisk(String level) => switch (level) {
        'red' => dangerSoft,
        'amber' => warningSoft,
        _ => okSoft,
      };
}

class AppSpacing {
  const AppSpacing._();

  static const double xs = 4;
  static const double sm = 8;
  static const double md = 12;
  static const double lg = 16;
  static const double xl = 24;
  static const double xxl = 32;

  static const double radiusSm = 8;
  static const double radiusMd = 12;
  static const double radiusLg = 16;
  static const double radiusXl = 24;
}

class AppTheme {
  const AppTheme._();

  static ThemeData get light {
    final ColorScheme scheme = ColorScheme.fromSeed(
      seedColor: AppColors.primary,
      primary: AppColors.primary,
      surface: AppColors.surface,
      error: AppColors.danger,
    );
    return _base(scheme).copyWith(
      scaffoldBackgroundColor: AppColors.background,
      dividerColor: AppColors.divider,
      cardTheme: _cardTheme(AppColors.surface),
      appBarTheme: _appBarTheme(AppColors.background, AppColors.textPrimary),
      bottomNavigationBarTheme: const BottomNavigationBarThemeData(
        backgroundColor: AppColors.surface,
        selectedItemColor: AppColors.primary,
        unselectedItemColor: AppColors.textTertiary,
        type: BottomNavigationBarType.fixed,
        elevation: 8,
      ),
      inputDecorationTheme: _inputTheme(AppColors.surface, AppColors.divider),
    );
  }

  static ThemeData get dark {
    final ColorScheme scheme = ColorScheme.fromSeed(
      seedColor: AppColors.primary,
      brightness: Brightness.dark,
      surface: AppColors.darkSurface,
      error: AppColors.danger,
    );
    return _base(scheme).copyWith(
      scaffoldBackgroundColor: AppColors.darkBackground,
      dividerColor: AppColors.darkDivider,
      cardTheme: _cardTheme(AppColors.darkSurface),
      appBarTheme: _appBarTheme(AppColors.darkBackground, AppColors.darkTextPrimary),
      bottomNavigationBarTheme: const BottomNavigationBarThemeData(
        backgroundColor: AppColors.darkSurface,
        selectedItemColor: AppColors.primary,
        unselectedItemColor: AppColors.darkTextSecondary,
        type: BottomNavigationBarType.fixed,
        elevation: 8,
      ),
      inputDecorationTheme: _inputTheme(AppColors.darkSurfaceAlt, AppColors.darkDivider),
    );
  }

  static ThemeData _base(ColorScheme scheme) {
    return ThemeData(
      useMaterial3: true,
      colorScheme: scheme,
      visualDensity: VisualDensity.standard,
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          // 52dp: comfortable for older patients and for one-handed use.
          minimumSize: const Size.fromHeight(52),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppSpacing.radiusMd),
          ),
          textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          minimumSize: const Size.fromHeight(52),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppSpacing.radiusMd),
          ),
          textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          textStyle: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
        ),
      ),
      chipTheme: ChipThemeData(
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppSpacing.radiusSm),
        ),
      ),
      snackBarTheme: SnackBarThemeData(
        behavior: SnackBarBehavior.floating,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppSpacing.radiusMd),
        ),
      ),
    );
  }

  static CardTheme _cardTheme(Color color) => CardTheme(
        color: color,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppSpacing.radiusLg),
        ),
      );

  static AppBarTheme _appBarTheme(Color background, Color foreground) => AppBarTheme(
        backgroundColor: background,
        foregroundColor: foreground,
        elevation: 0,
        scrolledUnderElevation: 0.5,
        centerTitle: false,
        titleTextStyle: TextStyle(
          color: foreground,
          fontSize: 20,
          fontWeight: FontWeight.w700,
        ),
      );

  static InputDecorationTheme _inputTheme(Color fill, Color border) =>
      InputDecorationTheme(
        filled: true,
        fillColor: fill,
        contentPadding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.lg,
          vertical: AppSpacing.lg,
        ),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppSpacing.radiusMd),
          borderSide: BorderSide(color: border),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppSpacing.radiusMd),
          borderSide: BorderSide(color: border),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppSpacing.radiusMd),
          borderSide: const BorderSide(color: AppColors.primary, width: 1.6),
        ),
        errorBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppSpacing.radiusMd),
          borderSide: const BorderSide(color: AppColors.danger),
        ),
      );
}
