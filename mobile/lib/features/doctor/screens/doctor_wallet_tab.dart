import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/l10n/app_localizations.dart';
import '../../../core/providers.dart';
import '../../../core/theme/app_theme.dart';
import '../../../data/models/models.dart';
import '../../../shared/utils/formatters.dart';
import '../../../shared/widgets/common_widgets.dart';
import '../../../shared/widgets/loading_view.dart';

/// Tab 3 — "Hamyon" (spec 4.2, spec 7).
///
/// The balance is an internal ledger, not a bank account: payouts are requested
/// here and settled manually by finance in the MVP.
class DoctorWalletTab extends ConsumerWidget {
  const DoctorWalletTab({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AppLocalizations l10n = context.l10n;
    final AsyncValue<Wallet> wallet = ref.watch(walletProvider);
    final AsyncValue<Paged<WalletTransaction>> transactions =
        ref.watch(walletTransactionsProvider);

    return Scaffold(
      appBar: AppBar(title: Text(l10n.t('doctor.tab_wallet'))),
      body: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(walletProvider);
          ref.invalidate(walletTransactionsProvider);
        },
        child: ListView(
          padding: const EdgeInsets.all(AppSpacing.lg),
          children: <Widget>[
            AsyncView<Wallet>(
              value: wallet,
              onRetry: () => ref.invalidate(walletProvider),
              builder: (Wallet data) => _BalanceCard(wallet: data),
            ),
            SectionHeader(title: l10n.t('doctor.transactions')),
            AsyncView<Paged<WalletTransaction>>(
              value: transactions,
              loading: const LinearProgressIndicator(minHeight: 2),
              builder: (Paged<WalletTransaction> page) {
                if (page.items.isEmpty) {
                  return AppCard(
                    child: Center(
                      child: Text(
                        l10n.t('doctor.no_transactions'),
                        style: const TextStyle(color: AppColors.textTertiary),
                      ),
                    ),
                  );
                }
                return Column(
                  children: page.items
                      .map(
                        (WalletTransaction transaction) => Padding(
                          padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                          child: _TransactionRow(transaction: transaction),
                        ),
                      )
                      .toList(),
                );
              },
            ),
          ],
        ),
      ),
    );
  }
}

class _BalanceCard extends ConsumerWidget {
  const _BalanceCard({required this.wallet});

  final Wallet wallet;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AppLocalizations l10n = context.l10n;

    return Container(
      padding: const EdgeInsets.all(AppSpacing.xl),
      decoration: BoxDecoration(
        gradient: const LinearGradient(
          colors: <Color>[AppColors.primary, AppColors.primaryDark],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
        borderRadius: BorderRadius.circular(AppSpacing.radiusLg),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
            l10n.t('doctor.balance'),
            style: TextStyle(
              color: Colors.white.withValues(alpha: 0.85),
              fontSize: 13,
            ),
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            Formatters.money(wallet.balanceUzs, l10n.languageCode),
            style: const TextStyle(
              color: Colors.white,
              fontSize: 32,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: AppSpacing.xl),
          SizedBox(
            width: double.infinity,
            child: FilledButton.icon(
              style: FilledButton.styleFrom(
                backgroundColor: Colors.white,
                foregroundColor: AppColors.primaryDark,
              ),
              // Only active above the minimum threshold (spec 7).
              onPressed: wallet.canRequestPayout
                  ? () => _openPayout(context, ref, wallet)
                  : null,
              icon: const Icon(Icons.account_balance_rounded, size: 20),
              label: Text(l10n.t('doctor.withdraw')),
            ),
          ),
          if (!wallet.canRequestPayout) ...<Widget>[
            const SizedBox(height: AppSpacing.sm),
            Text(
              l10n.tp('doctor.min_payout', <String, Object?>{
                'amount': Formatters.money(
                  wallet.minPayoutUzs,
                  l10n.languageCode,
                ),
              }),
              style: TextStyle(
                color: Colors.white.withValues(alpha: 0.8),
                fontSize: 12,
              ),
            ),
          ],
        ],
      ),
    );
  }

  Future<void> _openPayout(
    BuildContext context,
    WidgetRef ref,
    Wallet wallet,
  ) async {
    final bool? requested = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (_) => _PayoutSheet(wallet: wallet),
    );
    if (requested ?? false) {
      ref.invalidate(walletProvider);
      ref.invalidate(walletTransactionsProvider);
    }
  }
}

class _PayoutSheet extends ConsumerStatefulWidget {
  const _PayoutSheet({required this.wallet});

  final Wallet wallet;

  @override
  ConsumerState<_PayoutSheet> createState() => _PayoutSheetState();
}

class _PayoutSheetState extends ConsumerState<_PayoutSheet> {
  final GlobalKey<FormState> _formKey = GlobalKey<FormState>();
  late final TextEditingController _amount = TextEditingController(
    text: '${widget.wallet.balanceUzs}',
  );
  final TextEditingController _card = TextEditingController();
  final TextEditingController _holder = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _amount.dispose();
    _card.dispose();
    _holder.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() => _busy = true);
    try {
      await ref.read(billingRepositoryProvider).requestPayout(
            amountUzs: int.parse(_amount.text.trim()),
            cardNumber: _card.text.replaceAll(RegExp(r'\D'), ''),
            cardHolder: _holder.text.trim(),
          );
      if (mounted) {
        showSuccess(context, context.l10n.t('common.done'));
        Navigator.of(context).pop(true);
      }
    } catch (error) {
      if (mounted) showApiError(context, error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = context.l10n;

    return Padding(
      padding: EdgeInsets.only(
        left: AppSpacing.xl,
        right: AppSpacing.xl,
        top: AppSpacing.xl,
        bottom: MediaQuery.of(context).viewInsets.bottom + AppSpacing.xl,
      ),
      child: Form(
        key: _formKey,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            Text(
              l10n.t('doctor.withdraw_title'),
              style: Theme.of(context).textTheme.titleLarge?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
            ),
            const SizedBox(height: AppSpacing.lg),
            TextFormField(
              controller: _amount,
              keyboardType: TextInputType.number,
              inputFormatters: <TextInputFormatter>[
                FilteringTextInputFormatter.digitsOnly,
              ],
              decoration: InputDecoration(
                labelText: l10n.t('doctor.amount'),
                suffixText: l10n.t('common.sum'),
              ),
              validator: (String? value) {
                final int? parsed = int.tryParse(value?.trim() ?? '');
                if (parsed == null || parsed < widget.wallet.minPayoutUzs) {
                  return l10n.t('error.payout_below_minimum');
                }
                if (parsed > widget.wallet.balanceUzs) {
                  return l10n.t('error.insufficient_balance');
                }
                return null;
              },
            ),
            const SizedBox(height: AppSpacing.lg),
            TextFormField(
              controller: _card,
              keyboardType: TextInputType.number,
              inputFormatters: <TextInputFormatter>[
                FilteringTextInputFormatter.allow(RegExp(r'[\d\s]')),
                LengthLimitingTextInputFormatter(19),
              ],
              decoration: InputDecoration(
                labelText: l10n.t('doctor.card_number'),
                hintText: '8600 XXXX XXXX XXXX',
              ),
              validator: (String? value) {
                final String digits = (value ?? '').replaceAll(RegExp(r'\D'), '');
                return digits.length < 12 ? l10n.t('error.required_field') : null;
              },
            ),
            const SizedBox(height: AppSpacing.lg),
            TextFormField(
              controller: _holder,
              textCapitalization: TextCapitalization.characters,
              decoration: InputDecoration(
                labelText: l10n.t('doctor.card_holder'),
              ),
              validator: (String? value) => Validators.minLength(
                value,
                2,
                l10n.t('error.required_field'),
              ),
            ),
            const SizedBox(height: AppSpacing.xl),
            FilledButton(
              onPressed: _busy ? null : _submit,
              child: Text(l10n.t('doctor.send_request')),
            ),
          ],
        ),
      ),
    );
  }
}

class _TransactionRow extends StatelessWidget {
  const _TransactionRow({required this.transaction});

  final WalletTransaction transaction;

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = context.l10n;
    final bool credit = transaction.isCredit;

    return AppCard(
      padding: const EdgeInsets.all(AppSpacing.md),
      child: Row(
        children: <Widget>[
          Container(
            width: 38,
            height: 38,
            decoration: BoxDecoration(
              color: (credit ? AppColors.ok : AppColors.textTertiary)
                  .withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(AppSpacing.radiusSm),
            ),
            child: Icon(
              credit ? Icons.arrow_downward_rounded : Icons.arrow_upward_rounded,
              size: 18,
              color: credit ? AppColors.ok : AppColors.textSecondary,
            ),
          ),
          const SizedBox(width: AppSpacing.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Text(
                  transaction.counterpartyName ??
                      transaction.description ??
                      transaction.type,
                  style: const TextStyle(fontWeight: FontWeight.w600),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                Text(
                  Formatters.relative(
                    transaction.createdAt,
                    l10n.languageCode,
                  ),
                  style: const TextStyle(
                    fontSize: 11.5,
                    color: AppColors.textTertiary,
                  ),
                ),
              ],
            ),
          ),
          MoneyText(
            amountUzs: transaction.amountUzs,
            showSign: true,
            style: TextStyle(
              fontWeight: FontWeight.w700,
              color: credit ? AppColors.ok : AppColors.textPrimary,
            ),
          ),
        ],
      ),
    );
  }
}
