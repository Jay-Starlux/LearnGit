# -*- coding: utf-8 -*-
# Part of Odoo. See COPYRIGHT & LICENSE files for full copyright and licensing details.

from .authorize_request import AuthorizeAPI

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    # ================ TEST Field +++++++++++++++
    # authorize_payment_method_type = fields.Selection(
    #     string="Authorize.Net Payment Type",
    #     help="The type of payment method this token is linked to.",
    #     selection=[("credit_card", "Credit Card"), ("bank_account", "Bank Account (USA Only)")],
    # )
    # ================ TEST Field +++++++++++++++

    @api.model
    def search_fetch(self, domain, field_names, offset=0, limit=None, order=None):
        context = dict(self.env.context)
        company_id = self.env.company
        if context.get('authorize_payment_type') and context.get('authorize_payment_type') in ['credit_card', 'bank_account']:
            provider_ids = self.env['payment.provider'].with_context({'return_providers': True})._get_authorize_provider(company_id=company_id)
            bank_payment_method_id = self.env.ref("payment.payment_method_ach_direct_debit")
            cc_payment_method_id = self.env.ref("payment.payment_method_card")
            payment_method_id = cc_payment_method_id if context.get('authorize_payment_type') == 'credit_card' else bank_payment_method_id
            provider_ids = provider_ids.filtered(lambda x: payment_method_id and x.payment_method_ids and payment_method_id.id in x.payment_method_ids.ids)
            domain = (domain or []) + [('id', 'in', provider_ids.ids)]
        if context.get('cim_provider_partner'):
            partner_id = self.env['res.partner'].sudo().browse(context['cim_provider_partner'])
            provider_ids = self.env['payment.provider'].with_context({'return_providers': True})._get_authorize_provider(company_id=company_id)
            authorize_partner_ids = partner_id.authorize_partner_ids
            cim_provider_ids = authorize_partner_ids.mapped('provider_id')
            provider_ids -= cim_provider_ids
            domain = (domain or []) + [('id', 'in', provider_ids.ids)]
        if context.get('auth_payment_method_id'):
            provider_ids = self.env['payment.provider'].with_context({'return_providers': True})._get_authorize_provider(company_id=company_id)
            provider_ids = provider_ids.filtered(lambda x: x.payment_method_ids and context.get('auth_payment_method_id') in x.payment_method_ids.ids)
            domain = (domain or []) + [('id', 'in', provider_ids.ids)]
        return super().search_fetch(domain, field_names, offset, limit, order)

    @api.model
    def _name_search(self, name, domain=None, operator='ilike', limit=None, order=None):
        context = dict(self.env.context)
        company_id = self.env.company
        if context.get('authorize_payment_type') and context.get('authorize_payment_type') in ['credit_card', 'bank_account']:
            provider_ids = self.env['payment.provider'].with_context({'return_providers': True})._get_authorize_provider(company_id=company_id)
            bank_payment_method_id = self.env.ref("payment.payment_method_ach_direct_debit")
            cc_payment_method_id = self.env.ref("payment.payment_method_card")

            payment_method_id = cc_payment_method_id if context.get('authorize_payment_type') == 'credit_card' else bank_payment_method_id
            provider_ids = provider_ids.filtered(lambda x: payment_method_id and x.payment_method_ids and payment_method_id.id in x.payment_method_ids.ids)
            domain = (domain or []) + [('id', 'in', provider_ids.ids)]
        if context.get('cim_provider_partner'):
            partner_id = self.env['res.partner'].sudo().browse(context['cim_provider_partner'])
            provider_ids = self.env['payment.provider'].with_context({'return_providers': True})._get_authorize_provider(company_id=company_id)
            authorize_partner_ids = partner_id.authorize_partner_ids
            cim_provider_ids = authorize_partner_ids.mapped('provider_id')
            provider_ids -= cim_provider_ids
            domain = (domain or []) + [('id', 'in', provider_ids.ids)]
        if context.get('auth_payment_method_id'):
            provider_ids = self.env['payment.provider'].with_context({'return_providers': True})._get_authorize_provider(company_id=company_id)
            provider_ids = provider_ids.filtered(lambda x: x.payment_method_ids and context.get('auth_payment_method_id') in x.payment_method_ids.ids)
            domain = (domain or []) + [('id', 'in', provider_ids.ids)]
        return super()._name_search(name, domain, operator, limit, order)

    def _get_authorize_provider(self, company_id=False, provider_type='credit_card'):
        context = dict(self.env.context)
        if not company_id:
            company_id = self.env.company
        domain = [('code', '=', 'authorize'), ('company_id', '=', company_id.id), ('state', '!=', 'disabled')]
        providers = self.sudo().search(domain)
        if context.get('return_providers'): return providers

        for provider in providers:
            if provider_type == "bank_account" and self.env.ref("payment.payment_method_ach_direct_debit") and \
                self.env.ref("payment.payment_method_ach_direct_debit").active and self.env.ref("payment.payment_method_ach_direct_debit").id in provider.payment_method_ids.ids:
                return provider
            if provider_type == "credit_card" and self.env.ref("payment.payment_method_card") and \
                self.env.ref("payment.payment_method_card").active and self.env.ref("payment.payment_method_card").id in provider.payment_method_ids.ids:
                return provider
            continue
        # =========== NEW ADDED +++++++++++++

    @api.onchange('company_id', 'code')
    def _onchange_company(self):
        if self.code == 'authorize' and self.company_id:
            return {
                'domain': {
                    'journal_id': [
                        ('type', '=', 'bank'),
                        ('company_id', '=', self.company_id.id)
                    ]
                }
            }
        else:
            return {
                'domain': {
                    'journal_id': [('type', 'in', ['bank', 'cash'])]
                }
            }

    @api.constrains('authorize_login', 'authorize_transaction_key')
    def _check_authorize_login(self):
        for rec in self:
            try:
                if rec.code == 'authorize':
                    journal_currency = False
                    if rec.authorize_login and rec.authorize_login != 'dummy' and rec.journal_id:
                        authorize_api = AuthorizeAPI(self)
                        journal_currency = rec.journal_id.currency_id.name
                        if not journal_currency:
                            journal_currency = rec.journal_id.company_id.currency_id.name
                        resp =  authorize_api.get_merchant_details()
                        if resp.get('resultCode') == 'Ok' and resp.get('x_currency') and resp['x_currency'][0] is not False:
                            merchant_currency = resp['x_currency'][0]
                            if journal_currency and merchant_currency and journal_currency != merchant_currency:
                                raise ValidationError(_("Do not Match Journal Currency and Merchant Acccount Currency."))
            except UserError as e:
                raise UserError(_(e.args[0]))
            except ValidationError as e:
                raise ValidationError(e.args[0])
            except Exception as e:
                raise UserError(_("Authorize.NET Error! : %s !" %e))
