# -*- coding: utf-8 -*-
# Part of Odoo. See COPYRIGHT & LICENSE files for full copyright and licensing details.

from odoo import api, fields, models


class AuthorizeShippingPartner(models.TransientModel):
    _name = "authorize.shipping.partner"
    _description = "Authorize Shipping Partner"

    # @api.model
    # def default_get(self, fields):
    #     res = super(AuthorizeShippingPartner, self).default_get(fields)
    #     context = dict(self.env.context)
    #     if context.get('active_id') and context.get('active_model') == 'res.partner':
    #         res['partner_id'] = context['active_id']
    #     authorize_partner_id = False
    #     if context.get('active_id') and context.get('active_model') == 'res.partner.authorize':
    #         res['authorize_partner_id'] = context['active_id']
    #         authorize_partner_id = self.env['res.partner.authorize'].sudo().browse(int(context['active_id']))
    #     if authorize_partner_id:
    #         res['company_id'] = authorize_partner_id.company_id and authorize_partner_id.company_id.id or False
    #         res['provider_id'] = authorize_partner_id.provider_id and authorize_partner_id.provider_id.id or False
    #     else:
    #         company_id = self.company_id or self.env.company or False
    #         provider_id = self.env['payment.provider']._get_authorize_provider(company_id=company_id)
    #         bank_provider_id = self.env['payment.provider']._get_authorize_provider(company_id=company_id, provider_type="bank_account")
    #         res['company_id'] = company_id and company_id.id or False
    #         res['provider_id'] = provider_id and provider_id.id or False
    #         res['bank_provider_id'] = bank_provider_id and bank_provider_id.id or False
    #     return res

    @api.model
    def default_get(self, fields):
        res = super(AuthorizeShippingPartner, self).default_get(fields)
        context = dict(self.env.context)

        partner_id = False
        if context.get('active_id') and context.get('active_model') == 'res.partner':
            partner_id = self.env['res.partner'].sudo().browse(context['active_id'])
            res['partner_id'] = context['active_id']

        authorize_partner_id = False
        if context.get('active_id') and context.get('active_model') == 'res.partner.authorize':
            res['authorize_partner_id'] = context['active_id']
            authorize_partner_id = self.env['res.partner.authorize'].sudo().browse(int(context['active_id']))

        if authorize_partner_id:
            res['company_id'] = authorize_partner_id.company_id and authorize_partner_id.company_id.id or False
            res['provider_id'] = authorize_partner_id.provider_id and authorize_partner_id.provider_id.id or False
        else:
            company_id = self.company_id or self.env.company or False
            provider_ids = self.env['payment.provider'].with_context({'return_providers': True})._get_authorize_provider(company_id=company_id)
            authorize_partner_ids = partner_id.authorize_partner_ids
            cim_provider_ids = authorize_partner_ids.mapped('provider_id')
            provider_ids -= cim_provider_ids

            res['provider_id'] = provider_ids and provider_ids[0].id or False
            res['company_id'] = company_id and company_id.id or False
        return res

    def _get_shipping_partner_domain(self):
        domain = [('type', '=', 'delivery')]
        if self._context.get('active_id') and self._context.get('active_model') == 'res.partner':
            domain.append(('parent_id', '=', self._context['active_id']))
        return domain

    partner_id = fields.Many2one('res.partner', 'Partner')
    authorize_partner_id = fields.Many2one('res.partner.authorize', string='Authorize Partner')
    shipping_partner_id = fields.Many2one('res.partner', 'Shipping Partner', domain=_get_shipping_partner_domain)
    company_id = fields.Many2one('res.company', string='Company', required=True, store=True, index=True)
    provider_id = fields.Many2one('payment.provider', string="Provider", required=True)

    def add_shipping_authorize_cust(self):
        """ Add shipping details on creating a customer profile from Authorize.net """
        self.ensure_one()
        if self.authorize_partner_id:
            self.authorize_partner_id.update_authorize(provider=self.provider_id, shipping_address_id=self.shipping_partner_id)
        else:
            if self.provider_id and self.partner_id:
                self.partner_id.authorize_customer_create(provider=self.provider_id, shipping_address_id=self.shipping_partner_id)
