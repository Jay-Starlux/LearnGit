# -*- coding: utf-8 -*-
# Part of Odoo. See COPYRIGHT & LICENSE files for full copyright and licensing details.

import logging

from .authorize_request import AuthorizeAPI

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class SaleOrderAuthRefund(models.Model):
    _name = "authorize.refund"
    _description = "Authorize refund"

    @api.model
    def default_get(self, fields):
        res = super(SaleOrderAuthRefund, self).default_get(fields)
        transaction_ids = []
        context = dict(self.env.context or {})
        if context.get('active_id') and context.get('active_model') == 'sale.order':
            sale_order_id = self.env['sale.order'].browse(context['active_id'])
            for tx_id in sale_order_id.transaction_ids.sudo().filtered(lambda tx: tx.transaction_type == 'debit' and \
                    not tx.echeck_transaction and not tx.refund_amount >= tx.amount and tx.state == 'done' and \
                    tx.payment_id and (tx.payment_id.payment_method_type_id and tx.payment_id.payment_method_type_id.id == self.env.ref("payment.payment_method_card").id)):
                remaining_amount = tx_id.amount - tx_id.refund_amount
                cim_id = tx_id.partner_id.authorize_partner_ids.filtered(lambda x: x.company_id and x.provider_id and \
                            x.company_id.id == tx_id.company_id.id and x.provider_id.id == tx_id.provider_id.id)
                if remaining_amount:
                    vals = {
                        'partner_id': tx_id.partner_id.id,
                        'transaction_id': tx_id.provider_reference,
                        'payment_token_id': tx_id.token_id and tx_id.token_id.id,
                        'credit_amount': tx_id.amount,
                        'refund_amount': remaining_amount,
                        'available_amount': remaining_amount,
                        'payment_transaction_id': tx_id.id,
                        'company_id': tx_id.company_id.id,
                        'provider_id': tx_id.provider_id.id,
                        'currency_id': tx_id.currency_id.id,
                        'customer_profile_id': cim_id.customer_profile_id if cim_id else transaction.payment_id.customer_profile_id,
                        'merchant_id': cim_id.merchant_id if cim_id else transaction.payment_id.merchant_id,
                    }
                    auth_invoice_refund_id = self.env['authorize.invoice.refund'].create(vals)
                    transaction_ids.append(auth_invoice_refund_id.id)
            res.update({
                'auth_invoice_refund_ids': [(6, 0, transaction_ids)],
                'partner_id': sale_order_id.partner_id.id,
                'company_id': sale_order_id.company_id.id,
            })
        return res

    company_id = fields.Many2one('res.company', string='Company', index=True, copy=False)
    auth_invoice_refund_ids = fields.Many2many('authorize.invoice.refund', string="Transaction", ondelete='cascade')
    partner_id = fields.Many2one('res.partner', string="Partner")

    def auth_refund(self):
        self.ensure_one()
        try:
            context = dict(self.env.context or {})
            order_id = False
            if context.get('active_id') and context.get('active_model') == 'sale.order':
                order_id = self.env['sale.order'].browse(context['active_id'])

            if not self.auth_invoice_refund_ids:
                raise ValidationError(_('There are no refundable line.'))

            for rec in self.auth_invoice_refund_ids:
                if not rec.provider_id:
                    raise ValidationError(_("Please configure your Authorize.Net account."))
                if rec.provider_id and not rec.provider_id.journal_id:
                    raise ValidationError(_("Please configure Authorize Payment journal"))
                journal_id = rec.provider_id and rec.provider_id.journal_id

                # Convert Currency Amount
                from_currency_id = rec.currency_id
                to_currency_id = journal_id.currency_id or journal_id.company_id.currency_id
                currency_amount = rec.refund_amount
                if from_currency_id and to_currency_id and from_currency_id != to_currency_id:
                    currency_amount = from_currency_id._convert(rec.refund_amount, to_currency_id, journal_id.company_id, fields.Date.today())

                if rec.credit_amount and rec.refund_amount and rec.transaction_id and \
                    rec.payment_transaction_id and self.partner_id and order_id:
                    charge_data = {}
                    card_number = rec.payment_transaction_id.get_payment_transaction_details()
                    if card_number and rec.payment_transaction_id.provider_reference:
                        invoiceNumber = order_id.name[:19] + '/' if len(order_id.name) > 20 else order_id.name
                        description = (order_id.note or '' + ' ' + invoiceNumber or '' + ' Refund Tx') or (invoiceNumber or '' + ' Refund Tx' or '')
                        charge_data.update({
                            'amount': str(round(currency_amount, 2)),
                            'refId': str(rec.customer_profile_id) if rec.customer_profile_id else False,
                            'trans_id': str(rec.transaction_id),
                            'cc_number': str(card_number),
                            'expiry_date': 'XXXX',
                            'invoiceNumber': invoiceNumber,
                            'description': description and description[:255] or '',
                        })
                        authorize_api = AuthorizeAPI(rec.provider_id)
                        resp = authorize_api.refund_transaction(charge_data=charge_data)
                        if resp is not None:
                            transaction_id = self.env['payment.transaction'].create({
                                'partner_id': rec.partner_id.id,
                                'provider_id': rec.provider_id.id,
                                'amount': rec.refund_amount,
                                'transaction_type': 'credit',
                                'currency_id': rec.currency_id.id,
                                'sale_order_ids': [(4, order_id.id)],
                                'company_id': rec.provider_id.company_id.id,
                                'payment_method_id': rec.payment_transaction_id.payment_method_id.id,
                            })
                            refund_tran_id = resp.get('x_trans_id')
                            status_code = int(resp.get('x_response_code', '0'))
                            if refund_tran_id and status_code:
                                tx_vals = {'provider_reference': str(refund_tran_id)}
                                if rec.payment_token_id:
                                    tx_vals.update({'token_id': rec.payment_token_id.id})
                                transaction_id.write(tx_vals)
                                state_message = resp.get('x_response_reason_text', '')
                                if status_code == 1:
                                    transaction_id._set_done(state_message=state_message)

                                    order_id.write({'transaction_ids': [(4, transaction_id.id)]})
                                    rec.payment_transaction_id.refund_amount += round(currency_amount, 2)
                                    payment_id = transaction_id.create_payment_vals(\
                                        trans_id=str(refund_tran_id), \
                                        authorize_partner=rec, authorize_payment_type='credit_card')
                                    payment_id.action_post()
                                    transaction_id.payment_id = payment_id.id if payment_id else False
                                    transaction_id.is_post_processed = True
                                    _logger.info('Successfully created transaction with Transaction ID: %s', resp.get('x_trans_id'))
                                elif status_code == 4:
                                    # transaction_id.write({'state_message': resp.get('x_response_reason_text')})
                                    transaction_id._set_pending(state_message=state_message)
                                else:
                                    error = resp.get('x_response_reason_text', "Authorize Transaction Error")
                                    _logger.info(error)
                                    transaction_id._set_error(state_message=error)
                    else:
                        raise ValidationError(_('Failed to Refund Transaction.'))
        except UserError as e:
            raise UserError(_(e.args[0]))
        except ValidationError as e:
            raise ValidationError(e.args[0])
        except Exception as e:
            raise UserError(_("Authorize.NET Error! : %s !" % e))


class AuthorizeInvoiceRefund(models.Model):
    _name = "authorize.invoice.refund"
    _description = "Authorize Refund"

    provider_id = fields.Many2one('payment.provider', string='Provider', copy=False)
    company_id = fields.Many2one('res.company', related='provider_id.company_id', string='Company', index=True, copy=False)
    partner_id = fields.Many2one('res.partner', string="Customer", copy=False)
    transaction_id = fields.Char('Credit Transaction ID', copy=False)
    payment_token_id = fields.Many2one('payment.token', string='Credit Card', copy=False)
    credit_amount = fields.Float('Credit Amount', copy=False)
    refund_amount = fields.Float('Refund Amount', copy=False)
    available_amount = fields.Float('Available Refund Amount', copy=False)
    payment_transaction_id = fields.Many2one('payment.transaction')
    currency_id = fields.Many2one('res.currency', string='Currency')
    merchant_id = fields.Char(string='Merchant', readonly=True)
    customer_profile_id = fields.Char(string='Customer Profile ID', size=64, readonly=True)
    payment_method_id = fields.Many2one(related='payment_transaction_id.payment_method_id', comodel_name='payment.method', string="Payment Method", store=True)

    @api.constrains('refund_amount')
    def _check_available_refund(self):
        for rec in self:
            if rec.refund_amount and rec.credit_amount and rec.available_amount < rec.refund_amount:
                raise ValidationError(_('Please enter valid refund amount for transaction!'))

    @api.onchange('currency_id')
    def onchange_currency_id(self):
        if self.currency_id:
            from_currency_id = (self.payment_transaction_id and self.payment_transaction_id.currency_id) or self.provider_id.journal_id.currency_id
            to_currency_id = self.currency_id
            self.refund_amount = self.payment_transaction_id.amount - self.payment_transaction_id.refund_amount
            if from_currency_id and to_currency_id and from_currency_id != to_currency_id:
                self.refund_amount = from_currency_id._convert(self.payment_transaction_id.amount - self.payment_transaction_id.refund_amount, to_currency_id, self.company_id, fields.Date.today())
