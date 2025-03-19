# -*- coding: utf-8 -*-
# Part of Odoo. See COPYRIGHT & LICENSE files for full copyright and licensing details.

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    group_without_save_payment_options = fields.Boolean("Authorize.Net Direct Payment (Without Save Card)",
          implied_group='authorize_net.group_without_save_payment_options',
          help="Members of this group see the without save card payment and without save bank details payment options on Authorize.Net Backend Payment.")
