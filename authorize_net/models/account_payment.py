# -*- coding: utf-8 -*-
# Part of Odoo. See COPYRIGHT & LICENSE files for full copyright and licensing details.

import logging

from lxml import etree, html

from datetime import datetime
from .authorize_request import AuthorizeAPI
from odoo.addons.authorize_net.models import misc

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)


class AccountPayment(models.Model):
    _inherit = "account.payment"

    provider_id = fields.Many2one('payment.provider', string='Provider', copy=False)
    auth_partner_id = fields.Many2one('res.partner.authorize', string="Customer Profile", copy=False)
    payment_method_type_id = fields.Many2one('payment.method', string="Payment Method")
    authorize_payment_type = fields.Selection([('credit_card', 'Credit Card'),
                                ('bank_account', 'eCheck.Net')], string='Authorize Transaction',
                                 copy=False, readonly=True)
    transaction_type = fields.Selection([('authorize', 'Authorize'), ('capture', 'Capture'),
                        ('auth_capture', 'Authorize and Capture')], string='Transaction Type',
                        default='authorize', copy=False, readonly=True)
    merchant_id = fields.Char(string='Merchant', readonly=True, copy=False)
    customer_profile_id = fields.Char(string='Customer Profile ID', size=64, readonly=True, copy=False)
    shipping_address_id = fields.Char(string='Shipping ID', size=64, readonly=True, copy=False)
    payment_token_id = fields.Many2one('payment.token', string='Credit Card or Account',
                        domain="[('partner_id', '=', partner_id), '|', ('company_id', '=', False), \
                            ('company_id', '=', company_id)]", copy=False, readonly=True)
    transaction_id = fields.Char('Transaction ID', copy=False,
                        readonly=True)
    payment_authorize = fields.Boolean('Payment via Authorize.Net', copy=False)
    is_refund_ref = fields.Boolean('Is Refund Reference', copy=False)
    auth_invoice_refund_ids = fields.Many2many('authorize.invoice.refund',
                                string="Transaction", ondelete='cascade', copy=False)
    # without save card
    is_wo_save_card = fields.Boolean('Direct Payment(Without Save Card)', default=False, copy=False)
    cc_type = fields.Selection([('americanexpress', 'American Express'),
                                ('visa', 'Visa'),
                                ('mastercard', 'Mastercard'),
                                ('discover', 'Discover'),
                                ('dinersclub', 'Diners Club'),
                                ('jcb', 'JCB')], 'Card Type', readonly=True, copy=False)
    cc_number = fields.Char('Card Number', size=16, copy=False)
    cc_cvv = fields.Char('CVV', size=4, copy=False)
    cc_month = fields.Selection([('01', '01'), ('02', '02'), ('03', '03'), ('04', '04'),
                                 ('05', '05'), ('06', '06'), ('07', '07'), ('08', '08'),
                                 ('09', '09'), ('10', '10'), ('11', '11'), ('12', '12'),
                                 ('xx', 'xx')], 'Expires Month', copy=False)
    cc_year = fields.Char('Expires Year', size=64, copy=False)
    billing_partner_id = fields.Many2one('res.partner', 'Billing Partner')

    def _create_transaction(self, trans_id, invoice_id, provider=False, payment_method_id=False):
        provider_id = provider if provider else self.provider_id
        orders = invoice_id.line_ids.sale_line_ids.order_id
        values = {
            'partner_id': self.partner_id.id,
            'provider_id': provider_id and provider_id.id,
            'provider_reference': str(trans_id),
            'amount': self.amount,
            'transaction_type': 'debit',
            'currency_id': self.currency_id.id,
            'invoice_ids': [(6, 0, [invoice_id.id])],
            'sale_order_ids': [(6, 0, orders.ids)],
            'company_id': provider_id and provider_id.company_id and provider_id.company_id.id,
            'operation': 'online_direct',
            'payment_method_id': payment_method_id and payment_method_id.id or False,
        }
        transaction_id = self.env['payment.transaction'].create(values)
        return transaction_id

    def action_post(self):
        ''' Add code for post payment with authorized .net payment. '''
        context = dict(self.env.context or {})
        self.env.context = context
        payments_need_tx = self.filtered(
            lambda p: (p.payment_token_id and p.payment_authorize) or \
                (p.payment_authorize and p.payment_method_code == 'authorize' or \
                (p.payment_authorize and (p.payment_type == 'outbound' or p.provider_id.code == 'authorize')))
        )
        if context.get('is_register_pay') and payments_need_tx:
            payments_need_tx.sudo().post_payment_authorize()
            payments_trans_done = self.filtered(lambda pay: pay.payment_transaction_id and pay.payment_transaction_id.state == 'done')
            return super(AccountPayment, payments_trans_done).action_post()
        return super(AccountPayment, self).action_post()

    def _prepare_payment_transaction_vals(self, **extra_create_values):
        super()._prepare_payment_transaction_vals(**extra_create_values)
        self.ensure_one()
        transaction_ref = self.env['payment.transaction'].search([('reference', '=', self.ref)])
        provider_code = self.payment_token_id and self.payment_token_id.provider_id.code or self.provider_id.code or 'authorize'
        new_ref = transaction_ref._compute_reference(provider_code=provider_code, prefix=self.ref)
        vals = {
            'provider_id': self.payment_token_id.provider_id.id,
            'reference': self.ref if not transaction_ref else new_ref,
            'amount': self.amount,
            'currency_id': self.currency_id.id,
            'partner_id': self.partner_id.id,
            'token_id': self.payment_token_id.id,
            'operation': 'offline',
            'payment_id': self.id,
            **extra_create_values,
        }
        if self.payment_token_id and self.payment_token_id.provider_id and self.payment_token_id.provider_id.code == 'authorize':
            vals.update({'payment_method_id': self.payment_token_id.payment_method_id.id})

        return vals

    def post_payment_authorize(self):
        """Customer Register Payment"""
        context = dict(self.env.context or {})

        invoice_ids = False
        if context.get('active_model') == 'account.move':
            lines = self.env['account.move'].browse(context.get('active_ids', [])).line_ids
        elif context.get('active_model') == 'account.move.line':
            lines = self.env['account.move.line'].browse(context.get('active_ids', []))

        if lines:
            invoice_ids = lines.mapped('move_id')

        # if context.get('active_id') and context.get('active_model') == 'account.move':
        if context.get('is_register_pay') and invoice_ids and len(invoice_ids.ids) == 1:
            invoice_id = invoice_ids[0]
            for rec in self:
                # invoice_id = self.env['account.move'].browse(context['active_id'])
                response = {}
                # Credit Authorize Invoice Payment
                if rec.provider_id and invoice_id and \
                        invoice_id.move_type in ['out_invoice', 'in_invoice']:

                    journal_id = rec.journal_id or rec.provider_id and rec.provider_id.journal_id or False
                    if not rec.provider_id or not journal_id:
                        raise ValidationError(_("Please configure your Authorize.Net provider with account journal."))

                    # Convert Currency Amount
                    from_currency_id = rec.currency_id or rec.company_id.currency_id
                    to_currency_id = rec.provider_id.journal_id.currency_id or rec.provider_id.journal_id.company_id.currency_id
                    currency_amount = rec.amount
                    if from_currency_id and to_currency_id and from_currency_id != to_currency_id:
                        currency_amount = from_currency_id._convert(rec.amount, to_currency_id, rec.provider_id.journal_id.company_id, fields.Date.today())

                    # currency_amount = rec.amount
                    if not invoice_id.name and invoice_id.invoice_line_ids:
                        raise ValidationError(_("Require fields:: Invoice Number or product of Invoice"))

                    try:
                        charge_data = {
                            'invoiceNumber': invoice_id.name[:19] + '/' if invoice_id and len(invoice_id.name) > 20 else (invoice_id.name or ''),
                            'description': invoice_id.narration and invoice_id.narration[:255] or invoice_id.name and invoice_id.name[:255] or '',
                            'amount': str(round(currency_amount, 2)),
                            'refId': str(rec.merchant_id)
                        }

                        lines = {'lineItem': []}
                        count = 0
                        for item in invoice_id.invoice_line_ids:
                            count += 1
                            if not item.product_id:
                                continue
                            if item and item.product_id:
                                itemId = item.product_id.default_code or str(item.product_id.id) or ''
                                lines['lineItem'].append({
                                    'itemId': itemId[:30] + '/' if len(itemId) > 31 else itemId,
                                    'name': item.product_id.name[:30] + '/' if len(item.product_id.name) > 31 else item.product_id.name,
                                    'description': item.name[:254] + '/'  if len(item.name) > 255 else item.name,
                                    'quantity': str(item.quantity).replace('-', ''),
                                    'unitPrice': str(item.price_unit).replace('-', ''),
                                })
                            if count == 30:
                                break
                        charge_data.update({
                            'line_items': lines,
                            'shipping_address_id': invoice_id.partner_shipping_id
                        })
                        if rec.is_wo_save_card:
                            expiry_date = rec.cc_year + '-' + rec.cc_month
                            if datetime.now().strftime('%Y%m') > datetime.strptime(expiry_date, '%Y-%m').strftime('%Y%m'):
                                raise ValidationError(_("Expiration date not valid."))
                            billing_detail = rec.partner_id.get_partner_billing_address(rec.billing_partner_id)
                            # Create the payment data for a credit card
                            card_details = {
                                'card_number': str(rec.cc_number),
                                'expiry_date': expiry_date,
                                'card_code': rec.cc_cvv
                            }
                            charge_data.update({'billing': billing_detail.get('billing')})
                            authorize_api = AuthorizeAPI(rec.provider_id)
                            response = authorize_api.auth_and_capture_charge(charge_data=charge_data, card_details=card_details)

                        elif rec.payment_token_id and rec.payment_token_id.provider_ref and rec.payment_token_id.provider_ref != 'dummy':
                            authorize_api = AuthorizeAPI(rec.provider_id)
                            charge_data.update({
                                'customer_profile_id': str(rec.customer_profile_id),
                                'paymentProfileId': rec.payment_token_id.provider_ref
                            })
                            response = authorize_api.auth_and_capture_charge(charge_data=charge_data)

                        trans_id = response.get('x_trans_id')
                        status_code = int(response.get('x_response_code', '0'))
                        if trans_id and status_code:
                            transaction_id = rec._create_transaction(trans_id=trans_id, invoice_id=invoice_id, payment_method_id=rec.payment_method_type_id)
                            if status_code == 1:
                                transaction_id._set_done(state_message=response.get('x_response_reason_text', ''))
                                if not rec.is_wo_save_card:
                                    transaction_id.token_id = rec.payment_token_id and rec.payment_token_id.id or False
                                invoice_id.write({'transaction_ids': [(4, transaction_id.id)]})
                                rec.update({
                                    'payment_transaction_id': transaction_id.id,
                                    'company_id': rec.company_id.id,
                                    'transaction_id': trans_id or '',
                                    # 'authorize_payment_type': 'credit_card',
                                    'transaction_type': 'auth_capture',
                                })
                                transaction_id.write({
                                    'payment_id': rec.id,
                                    'is_post_processed': True
                                })
                            elif status_code == 4:
                                transaction_id._set_pending(state_message='')
                            else:
                                error = response.get('x_response_reason_text', "Authorize Transaction Error")
                                _logger.info(error)
                                transaction_id._set_error(state_message=error)

                    except UserError as e:
                        raise UserError(_(e.args[0]))
                    except ValidationError as e:
                        raise ValidationError(e.args[0])
                    except Exception as e:
                        raise UserError(_("Authorize.NET Error! : %s !" % e))
                # Refund Authorize Invoice Payment
                elif invoice_id and invoice_id.move_type in ['out_refund', 'in_refund']:
                    self.ensure_one()
                    try:
                        charge_data = {}
                        count = 0
                        for record in rec.auth_invoice_refund_ids:
                            count += 1
                            # Convert Currency Amount
                            from_currency_id = record.currency_id
                            to_currency_id = record.provider_id.journal_id.currency_id or record.provider_id.journal_id.company_id.currency_id
                            currency_amount = record.refund_amount
                            if from_currency_id and to_currency_id and from_currency_id != to_currency_id:
                                currency_amount = from_currency_id._convert(record.refund_amount, to_currency_id, record.provider_id.journal_id.company_id, fields.Date.today())

                            debit_tx_id = record.payment_transaction_id
                            card_number = debit_tx_id.get_payment_transaction_details()
                            if record.credit_amount and record.refund_amount and record.transaction_id \
                                and card_number and record.partner_id:
                                charge_data.update({
                                    'amount': str(round(currency_amount, 2)),
                                    'refId': str(record.customer_profile_id),
                                    'trans_id': str(record.transaction_id),
                                    'cc_number': str(card_number),
                                    'expiry_date': 'XXXX',
                                    'invoiceNumber': invoice_id.name[:19] + '/' if len(invoice_id.name) > 20 else (invoice_id.name or ''),
                                    'description': invoice_id.narration and invoice_id.narration[:255] or invoice_id.name and invoice_id.name[:255] or '',
                                })
                                authorize_api = AuthorizeAPI(record.provider_id)
                                response = authorize_api.refund_transaction(charge_data=charge_data)
                                if response is not {}:
                                    refund_tran_id = response.get('x_trans_id')
                                    status_code = int(response.get('x_response_code', '0'))
                                    transaction_id = rec._create_transaction(trans_id=refund_tran_id, invoice_id=invoice_id, \
                                                        provider=record.provider_id, payment_method_id=debit_tx_id.payment_method_id)
                                    if refund_tran_id and status_code:
                                        if record.payment_token_id:
                                            transaction_id.token_id = record.payment_token_id.id
                                        transaction_id.write({
                                            'transaction_type': 'credit',
                                            'amount': record.refund_amount,
                                            'currency_id': record.currency_id.id
                                        })
                                        if status_code == 1:
                                            transaction_id._set_done(state_message=response.get('x_response_reason_text', ''))
                                            if invoice_id and transaction_id:
                                                invoice_id.write({'transaction_ids': [(4, transaction_id.id)]})
                                                record.payment_transaction_id.refund_amount += round(currency_amount, 2)
                                                if count > 1:
                                                    payment_id = transaction_id.create_payment_vals(trans_id=str(refund_tran_id), authorize_partner=record)
                                                    payment_id.action_post()
                                                    if transaction_id.invoice_ids:
                                                        transaction_id.invoice_ids.filtered(lambda move: move.state == 'draft')._post()

                                                        (payment_id.line_ids + transaction_id.invoice_ids.line_ids) \
                                                            .filtered(lambda line: line.account_id == payment_id.destination_account_id and not line.reconciled) \
                                                            .reconcile()
                                                    transaction_id.reference = self.env['payment.transaction']._compute_reference(provider_code='authorize', prefix=invoice_id.name)
                                                    transaction_id.payment_id = payment_id.id if payment_id else False
                                                    transaction_id.is_post_processed = True
                                                else:
                                                    rec.update({
                                                        'amount': record.refund_amount,
                                                        'currency_id': record.currency_id.id,
                                                        'company_id': rec.company_id.id,
                                                        'transaction_id': refund_tran_id,
                                                        # 'authorize_payment_type': 'credit_card',
                                                        'merchant_id': record.merchant_id,
                                                        'customer_profile_id': record.customer_profile_id or '',
                                                        'payment_transaction_id': transaction_id.id,
                                                        'payment_token_id': transaction_id.token_id and transaction_id.token_id.id or None,
                                                    })
                                                    transaction_id.payment_id = rec.id
                                                    transaction_id.is_post_processed = True
                                            _logger.info('Successfully created transaction with Transaction ID: %s', refund_tran_id)
                                        elif status_code == 4:
                                            transaction_id._set_pending(state_message='')
                                        else:
                                            error = response.get('x_response_reason_text', "Authorize Transaction Error")
                                            _logger.info(error)
                                            transaction_id._set_error(state_message=error)
                    except UserError as e:
                        raise UserError(_(e.args[0]))
                    except ValidationError as e:
                        raise ValidationError(e.args[0])
                    except Exception as e:
                        raise UserError(_("Authorize.NET Error! : %s !" % e))
                rec.update({
                    'cc_number': '',
                    'cc_cvv': '',
                    'cc_type': '',
                    'cc_year': '',
                    'cc_month': ''
                })
        return True
