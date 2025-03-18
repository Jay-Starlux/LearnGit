# -*- coding: utf-8 -*-
# Part of Odoo. See COPYRIGHT & LICENSE files for full copyright and licensing details.

import logging

from .authorize_request import AuthorizeAPI

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class AuthorizeInvoiceVoid(models.Model):
    _name = "authorize.invoice.void"
    _description = "Void Transaction"

    @api.model
    def default_get(self, fields):
        res = super(AuthorizeInvoiceVoid, self).default_get(fields)
        transaction_ids = []
        context = dict(self.env.context or {})
        if context.get('active_id') and context.get('active_model') == 'sale.order':
            sale_order_id = self.env['sale.order'].browse(context['active_id'])
            for transaction in sale_order_id.transaction_ids.filtered(lambda tx: tx.state in ['done', 'authorized']):
                cim_id = transaction.partner_id.authorize_partner_ids.filtered(lambda x: x.company_id and x.provider_id and \
                            x.company_id.id == transaction.company_id.id and x.provider_id.id == transaction.provider_id.id)
                vals = {
                    'partner_id': transaction.partner_id.id,
                    'payment_transaction_id': transaction.id,
                    'transaction_id': transaction.provider_reference,
                    'payment_token_id': transaction.token_id.id,
                    'credit_amount': transaction.amount,
                    'company_id': transaction.company_id.id,
                    'provider_id': transaction.provider_id.id,
                    'customer_profile_id': cim_id.customer_profile_id if cim_id else transaction.payment_id.customer_profile_id,
                    'merchant_id': cim_id.merchant_id if cim_id else transaction.payment_id.merchant_id,
                }
                void_transaction_id = self.env['transaction.void'].create(vals)
                transaction_ids.append(void_transaction_id.id)
            res.update({
                'transaction_ref_ids': [(6, 0, transaction_ids)],
                'partner_id': sale_order_id.partner_id.id,
                'company_id': sale_order_id.company_id.id
            })
        return res

    company_id = fields.Many2one('res.company', 'Company', index=True, copy=False)
    transaction_ref_ids = fields.Many2many('transaction.void', string="Transaction", ondelete='cascade')
    partner_id = fields.Many2one('res.partner', string="Partner")

    def void_unsettled_payment(self):
        self.ensure_one()
        context = dict(self.env.context or {})
        sale_order_id = False
        if context.get('active_id') and context.get('active_model') == 'sale.order':
            sale_order_id = self.env['sale.order'].browse(context['active_id'])
        if not self.transaction_ref_ids:
            raise ValidationError(_('There are no voided line.'))
        for transaction_ref_id in self.transaction_ref_ids:
            if not transaction_ref_id.provider_id:
                raise ValidationError(_("Please Configure Your Authorize.Net Account."))
            payment_id = transaction_ref_id.payment_transaction_id and transaction_ref_id.payment_transaction_id.payment_id
            if not payment_id:
                payment_id = self.env['account.payment'].search([
                                ('transaction_id', '=', transaction_ref_id.transaction_id),
                                ('customer_profile_id', '=', transaction_ref_id.customer_profile_id)
                            ], limit=1)
            try:
                authorize_api = AuthorizeAPI(transaction_ref_id.provider_id)
                resp = authorize_api.void(transaction_ref_id.transaction_id)
                if resp is not None:
                    if resp.get('x_trans_id'):
                        if payment_id:
                            payment_id.move_id.button_draft()
                            payment_id.action_cancel()
                        transaction_ref_id.payment_transaction_id.state = 'cancel'
                        _logger.info('Successfully void transaction with Transaction ID: %s', resp.get('x_trans_id'))
                else:
                    raise UserError(_('You can not do void transaction because your transacton %s is settled on authorize.net.' % transaction_ref_id.transaction_id))
            except UserError as e:
                raise UserError(_(e.args[0]))
            except Exception as e:
                raise UserError(_("Authorize.NET Error! : %s !" % e))


class TransactionVoid(models.Model):
    _name = "transaction.void"
    _description = "Void Transaction Ref"

    partner_id = fields.Many2one('res.partner', string="Customer", copy=False)
    payment_transaction_id = fields.Many2one('payment.transaction', string='Payment Transaction', copy=False)
    transaction_id = fields.Char('Credit Transaction ID', copy=False)
    payment_token_id = fields.Many2one('payment.token', string='Credit Card', copy=False)
    credit_amount = fields.Float('Credit Amount', copy=False)
    provider_id = fields.Many2one('payment.provider', string='Provider', copy=False)
    company_id = fields.Many2one('res.company', 'Company', index=True, copy=False)
    merchant_id = fields.Char(string='Merchant', readonly=True)
    customer_profile_id = fields.Char(string='Customer Profile ID', size=64, readonly=True)
    payment_method_id = fields.Many2one(related='payment_transaction_id.payment_method_id', comodel_name='payment.method', string="Payment Method", store=True)
