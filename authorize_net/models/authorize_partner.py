# -*- coding: utf-8 -*-
# Part of Odoo. See COPYRIGHT & LICENSE files for full copyright and licensing details.

import time
import random
import logging

from .authorize_request import AuthorizeAPI

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class ResPartnerAuthorize(models.Model):
    _name = "res.partner.authorize"
    _description = "Authorize Customer"

    partner_id = fields.Many2one('res.partner', string='Customer')
    customer_profile_id = fields.Char('Customer Profile ID', size=64, copy=False)
    shipping_address_id = fields.Char('Shipping ID', size=64, copy=False)
    merchant_id = fields.Char('Customer ID', copy=False)
    provider_id = fields.Many2one('payment.provider', string="Provider", required=True)
    payment_method_ids = fields.Many2many(related='provider_id.payment_method_ids', string="Supported Payment Methods", readonly=True)
    journal_id = fields.Many2one(related="provider_id.journal_id", string="Journal")
    company_id = fields.Many2one('res.company', related='provider_id.company_id', string='Company', index=True, copy=False)
    is_diff_provider = fields.Boolean('Different Provider Use for Credit / Bank?')
    provider_type = fields.Char('Provider Type')

    @api.depends('partner_id','provider_type','customer_profile_id')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.partner_id.name + \
                    (rec.provider_type and (' - ' + rec.provider_type) or '') + \
                    (rec.customer_profile_id and (' - ' + rec.customer_profile_id) or '')

    def update_authorize(self, provider=None, shipping_address_id=None):
        self.ensure_one()

        shipping_address = self.partner_id.get_partner_shipping_address(shipping_address_id)
        if not self.provider_id:
            raise ValidationError(_('Please configure your Authorize.Net account'))

        if self.customer_profile_id and self.merchant_id:
            try:
                authorize_api = AuthorizeAPI(self.provider_id)
                resp = authorize_api.update_customer_profile(partner=self)
                if resp.get('result_code') == "Ok":
                    address_resp = authorize_api.update_customer_profile_shipping_address(partner=self, shipping=shipping_address.get('shipping'))
                    if address_resp.get('result_code') == "Ok":
                        _logger.info('Your shipping address information has been successfully updated in the Authorize.net customer profile')
            except UserError as e:
                raise UserError(_(e.args[0]))
            except ValidationError as e:
                raise ValidationError(e.args[0])
            except Exception as e:
                raise UserError(_("Authorize.NET Error! : %s !" % e))
            return True
        else:
            raise ValidationError(_("To Update, a Customer Profile and Merchant are required of the customer."))

    def unlink_authorize(self):
        self.ensure_one()
        if not self.provider_id:
            raise ValidationError(_('Please configure your Authorize.Net account'))
        if not self.user_has_groups('account.group_account_manager'):
            raise UserError(_("You cannot delete this record."))
        if self.customer_profile_id:
            try:
                authorize_api = AuthorizeAPI(self.provider_id)
                domain = [('partner_id', '=', self.partner_id.id),
                          ('company_id', '=', self.company_id.id),
                          ('customer_profile_id', '=', self.customer_profile_id)]
                # bank_ids = self.env['res.partner.bank'].search(domain).unlink()
                token_ids = self.env['payment.token'].search(domain).unlink()
                resp = authorize_api.unlink_customer_profile(partner=self)
                if resp.get('result_code') == "Ok":
                    self.unlink()
            except UserError as e:
                raise UserError(_(e.args[0]))
            except ValidationError as e:
                raise ValidationError(e.args[0])
            except Exception as e:
                raise UserError(_("Authorize.NET Error! : %s !" % e))
        return True
