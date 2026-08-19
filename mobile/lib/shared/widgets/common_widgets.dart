import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../core/l10n/app_localizations.dart';
import '../../core/theme/app_theme.dart';
import '../utils/formatters.dart';

/// Section heading with an optional trailing action.
class SectionHeader extends StatelessWidget {
  const SectionHeader({super.key, required this.title, this.action});

  final String title;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(
        bottom: AppSpacing.md,
        top: AppSpacing.lg,
      ),
      child: Row(
        children: <Widget>[
          Expanded(
            child: Text(
              title,
              style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
            ),
          ),
          if (action != null) action!,
        ],
      ),
    );
  }
}

class AppCard extends StatelessWidget {
  const AppCard({
    super.key,
    required this.child,
    this.onTap,
    this.padding = const EdgeInsets.all(AppSpacing.lg),
    this.border,
  });

  final Widget child;
  final VoidCallback? onTap;
  final EdgeInsets padding;
  final Color? border;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Material(
      color: theme.cardTheme.color,
      borderRadius: BorderRadius.circular(AppSpacing.radiusLg),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(AppSpacing.radiusLg),
        child: Container(
          padding: padding,
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(AppSpacing.radiusLg),
            border: Border.all(
              color: border ?? theme.dividerColor,
              width: border != null ? 1.4 : 1,
            ),
          ),
          child: child,
        ),
      ),
    );
  }
}

/// Traffic-light badge for the doctor's patient list.
class RiskBadge extends StatelessWidget {
  const RiskBadge({super.key, required this.level, this.compact = false});

  final String level;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final Color color = AppColors.forRisk(level);
    if (compact) {
      return Container(
        width: 10,
        height: 10,
        decoration: BoxDecoration(color: color, shape: BoxShape.circle),
      );
    }
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: AppColors.softForRisk(level),
        borderRadius: BorderRadius.circular(AppSpacing.radiusSm),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(color: color, shape: BoxShape.circle),
          ),
          const SizedBox(width: 6),
          Text(
            switch (level) {
              'red' => 'Diqqat',
              'amber' => 'Kuzatuv',
              _ => 'Barqaror',
            },
            style: TextStyle(
              color: color,
              fontSize: 12,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}

/// "Tasdiqlangan" / "Ko'rib chiqish kutilmoqda" (spec 2.3).
class VerificationChip extends StatelessWidget {
  const VerificationChip({super.key, required this.isVerified});

  final bool isVerified;

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = context.l10n;
    final Color color = isVerified ? AppColors.ok : AppColors.warning;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(AppSpacing.radiusSm),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          Icon(
            isVerified ? Icons.verified_rounded : Icons.schedule_rounded,
            size: 14,
            color: color,
          ),
          const SizedBox(width: 5),
          Text(
            l10n.t(isVerified ? 'common.verified' : 'common.unverified'),
            style: TextStyle(
              color: color,
              fontSize: 12,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}

class StarRating extends StatelessWidget {
  const StarRating({
    super.key,
    required this.rating,
    this.size = 16,
    this.count,
    this.onChanged,
  });

  final double? rating;
  final double size;
  final int? count;
  final ValueChanged<int>? onChanged;

  @override
  Widget build(BuildContext context) {
    final double value = rating ?? 0;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        for (int index = 1; index <= 5; index++)
          GestureDetector(
            onTap: onChanged == null ? null : () => onChanged!(index),
            child: Padding(
              padding: EdgeInsets.only(right: onChanged != null ? 6 : 1),
              child: Icon(
                value >= index
                    ? Icons.star_rounded
                    : (value >= index - 0.5
                        ? Icons.star_half_rounded
                        : Icons.star_outline_rounded),
                size: onChanged != null ? size * 2 : size,
                color: AppColors.warning,
              ),
            ),
          ),
        if (count != null && count! > 0) ...<Widget>[
          const SizedBox(width: 6),
          Text(
            '${value.toStringAsFixed(1)} ($count)',
            style: const TextStyle(
              fontSize: 12,
              color: AppColors.textSecondary,
            ),
          ),
        ],
      ],
    );
  }
}

/// Large, copyable code display used for both invite and connect codes.
class CodeDisplay extends StatelessWidget {
  const CodeDisplay({
    super.key,
    required this.code,
    this.onShare,
    this.hint,
  });

  final String code;
  final VoidCallback? onShare;
  final String? hint;

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = context.l10n;
    return Column(
      children: <Widget>[
        Container(
          width: double.infinity,
          padding: const EdgeInsets.symmetric(vertical: AppSpacing.xl),
          decoration: BoxDecoration(
            color: AppColors.primaryLight,
            borderRadius: BorderRadius.circular(AppSpacing.radiusLg),
            border: Border.all(color: AppColors.primary.withValues(alpha: 0.3)),
          ),
          child: Column(
            children: <Widget>[
              Text(
                code,
                style: const TextStyle(
                  fontSize: 40,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 6,
                  color: AppColors.primaryDark,
                ),
              ),
              if (hint != null) ...<Widget>[
                const SizedBox(height: AppSpacing.sm),
                Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: AppSpacing.lg,
                  ),
                  child: Text(
                    hint!,
                    textAlign: TextAlign.center,
                    style: const TextStyle(
                      fontSize: 13,
                      color: AppColors.textSecondary,
                    ),
                  ),
                ),
              ],
            ],
          ),
        ),
        const SizedBox(height: AppSpacing.lg),
        Row(
          children: <Widget>[
            Expanded(
              child: OutlinedButton.icon(
                onPressed: () async {
                  await Clipboard.setData(ClipboardData(text: code));
                  if (context.mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(content: Text(l10n.t('common.copied'))),
                    );
                  }
                },
                icon: const Icon(Icons.copy_rounded, size: 18),
                label: Text(l10n.t('common.copy')),
              ),
            ),
            if (onShare != null) ...<Widget>[
              const SizedBox(width: AppSpacing.md),
              Expanded(
                child: FilledButton.icon(
                  onPressed: onShare,
                  icon: const Icon(Icons.share_rounded, size: 18),
                  label: Text(l10n.t('common.share')),
                ),
              ),
            ],
          ],
        ),
      ],
    );
  }
}

/// Money amount, formatted with the locale's currency word.
class MoneyText extends StatelessWidget {
  const MoneyText({
    super.key,
    required this.amountUzs,
    this.style,
    this.showSign = false,
  });

  final int amountUzs;
  final TextStyle? style;
  final bool showSign;

  @override
  Widget build(BuildContext context) {
    final String text = Formatters.money(amountUzs, context.l10n.languageCode);
    final String prefix = showSign && amountUzs > 0 ? '+' : '';
    return Text('$prefix$text', style: style);
  }
}

class LanguagePicker extends StatelessWidget {
  const LanguagePicker({super.key, required this.onSelected, this.current});

  final ValueChanged<String> onSelected;
  final String? current;

  static const Map<String, String> _labels = <String, String>{
    'uz': "O'zbek",
    'ru': 'Русский',
    'en': 'English',
  };

  @override
  Widget build(BuildContext context) {
    final String active = current ?? context.l10n.languageCode;
    return PopupMenuButton<String>(
      onSelected: onSelected,
      tooltip: context.l10n.t('common.language'),
      itemBuilder: (BuildContext context) => _labels.entries
          .map(
            (MapEntry<String, String> entry) => PopupMenuItem<String>(
              value: entry.key,
              child: Row(
                children: <Widget>[
                  if (entry.key == active)
                    const Icon(Icons.check_rounded, size: 18)
                  else
                    const SizedBox(width: 18),
                  const SizedBox(width: AppSpacing.sm),
                  Text(entry.value),
                ],
              ),
            ),
          )
          .toList(),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
        decoration: BoxDecoration(
          border: Border.all(color: Theme.of(context).dividerColor),
          borderRadius: BorderRadius.circular(AppSpacing.radiusSm),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            const Icon(Icons.language_rounded, size: 16),
            const SizedBox(width: 6),
            Text(
              active.toUpperCase(),
              style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
            ),
          ],
        ),
      ),
    );
  }
}

/// Confirmation dialog. Returns true only on an explicit confirm.
Future<bool> confirmDialog(
  BuildContext context, {
  required String title,
  String? message,
  String? confirmLabel,
  bool destructive = false,
}) async {
  final AppLocalizations l10n = context.l10n;
  final bool? result = await showDialog<bool>(
    context: context,
    builder: (BuildContext context) => AlertDialog(
      title: Text(title),
      content: message == null ? null : Text(message),
      actions: <Widget>[
        TextButton(
          onPressed: () => Navigator.of(context).pop(false),
          child: Text(l10n.t('common.cancel')),
        ),
        FilledButton(
          style: destructive
              ? FilledButton.styleFrom(backgroundColor: AppColors.danger)
              : null,
          onPressed: () => Navigator.of(context).pop(true),
          child: Text(confirmLabel ?? l10n.t('common.confirm')),
        ),
      ],
    ),
  );
  return result ?? false;
}
