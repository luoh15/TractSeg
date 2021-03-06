import os, sys, inspect
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe()))))
if not parent_dir in sys.path: sys.path.insert(0, parent_dir)

from os.path import join
import numpy as np
from collections import OrderedDict

from lasagne.layers import InputLayer, ConcatLayer, Pool2DLayer, ReshapeLayer, DimshuffleLayer, NonlinearityLayer, DropoutLayer, Upscale2DLayer
# from lasagne.layers.dnn import Conv2DDNNLayer as ConvLayer
from lasagne.layers import Conv2DLayer as ConvLayer

import theano
import theano.tensor as T
import lasagne as L

from libs.Config import Config as C
from models.BaseModel import BaseModel
from libs.Layers import theano_f1_score
# from libs.Layers import theano_f1_score_soft
from libs.Layers import theano_binary_dice_per_instance_and_class
from libs.Layers import theano_binary_dice_per_instance_and_class_for_loss

class UNet_Multilabel_diceLoss(BaseModel):

    @staticmethod
    def get_UNet(n_input_channels=1, BATCH_SIZE=None, num_output_classes=2, pad='same', nonlinearity=L.nonlinearities.rectify,
                   input_dim=(128, 128), base_n_filters=128, do_dropout=False):

        net = OrderedDict()
        net['input'] = InputLayer((BATCH_SIZE, n_input_channels, input_dim[0], input_dim[1]))

        net['contr_1_1'] = ConvLayer(net['input'], base_n_filters, 3, nonlinearity=nonlinearity, pad=pad)
        net['contr_1_2'] = ConvLayer(net['contr_1_1'], base_n_filters, 3, nonlinearity=nonlinearity, pad=pad)
        net['pool1'] = Pool2DLayer(net['contr_1_2'], 2)

        net['contr_2_1'] = ConvLayer(net['pool1'], base_n_filters * 2, 3, nonlinearity=nonlinearity, pad=pad)
        net['contr_2_2'] = ConvLayer(net['contr_2_1'], base_n_filters * 2, 3, nonlinearity=nonlinearity, pad=pad)
        net['pool2'] = Pool2DLayer(net['contr_2_2'], 2)

        net['contr_3_1'] = ConvLayer(net['pool2'], base_n_filters * 4, 3, nonlinearity=nonlinearity, pad=pad)
        net['contr_3_2'] = ConvLayer(net['contr_3_1'], base_n_filters * 4, 3, nonlinearity=nonlinearity, pad=pad)
        net['pool3'] = Pool2DLayer(net['contr_3_2'], 2)

        net['contr_4_1'] = ConvLayer(net['pool3'], base_n_filters * 8, 3, nonlinearity=nonlinearity, pad=pad)
        net['contr_4_2'] = ConvLayer(net['contr_4_1'], base_n_filters * 8, 3, nonlinearity=nonlinearity, pad=pad)
        l = net['pool4'] = Pool2DLayer(net['contr_4_2'], 2)
        # the paper does not really describe where and how dropout is added. Feel free to try more options
        # if do_dropout:
        l = DropoutLayer(l, p=0.4)

        net['encode_1'] = ConvLayer(l, base_n_filters * 16, 3, nonlinearity=nonlinearity, pad=pad)
        net['encode_2'] = ConvLayer(net['encode_1'], base_n_filters * 16, 3, nonlinearity=nonlinearity, pad=pad)
        net['deconv1'] = Upscale2DLayer(net['encode_2'], 2)

        net['concat1'] = ConcatLayer([net['deconv1'], net['contr_4_2']], cropping=(None, None, "center", "center"))
        net['expand_1_1'] = ConvLayer(net['concat1'], base_n_filters * 8, 3, nonlinearity=nonlinearity, pad=pad)
        net['expand_1_2'] = ConvLayer(net['expand_1_1'], base_n_filters * 8, 3, nonlinearity=nonlinearity, pad=pad)
        net['deconv2'] = Upscale2DLayer(net['expand_1_2'], 2)

        net['concat2'] = ConcatLayer([net['deconv2'], net['contr_3_2']], cropping=(None, None, "center", "center"))
        net['expand_2_1'] = ConvLayer(net['concat2'], base_n_filters * 4, 3, nonlinearity=nonlinearity, pad=pad)
        net['expand_2_2'] = ConvLayer(net['expand_2_1'], base_n_filters * 4, 3, nonlinearity=nonlinearity, pad=pad)
        net['deconv3'] = Upscale2DLayer(net['expand_2_2'], 2)

        net['concat3'] = ConcatLayer([net['deconv3'], net['contr_2_2']], cropping=(None, None, "center", "center"))
        net['expand_3_1'] = ConvLayer(net['concat3'], base_n_filters * 2, 3, nonlinearity=nonlinearity, pad=pad)
        net['expand_3_2'] = ConvLayer(net['expand_3_1'], base_n_filters * 2, 3, nonlinearity=nonlinearity, pad=pad)
        net['deconv4'] = Upscale2DLayer(net['expand_3_2'], 2)

        net['concat4'] = ConcatLayer([net['deconv4'], net['contr_1_2']], cropping=(None, None, "center", "center"))
        net['expand_4_1'] = ConvLayer(net['concat4'], base_n_filters, 3, nonlinearity=nonlinearity, pad=pad)
        net['expand_4_2'] = ConvLayer(net['expand_4_1'], base_n_filters, 3, nonlinearity=nonlinearity, pad=pad)

        net['conv_5'] = ConvLayer(net['expand_4_2'], num_output_classes, 1, nonlinearity=None)  # (bs, nrClasses, x, y)
        net['dimshuffle'] = DimshuffleLayer(net['conv_5'], (1, 0, 2, 3))  # (nrClasses, bs, x, y)
        net['reshapeSeg'] = ReshapeLayer(net['dimshuffle'], (num_output_classes, -1))  # (nrClasses, bs*x*y)
        net['dimshuffle2'] = DimshuffleLayer(net['reshapeSeg'], (1, 0))  # (bs*x*y, nrClasses)

        #Watch out: here is another nonlinearity -> do not use layers before this layer!
        net['output_flat'] = NonlinearityLayer(net['dimshuffle2'], nonlinearity=L.nonlinearities.sigmoid)  # (bs*x*y, nrClasses)
        img_shape = net["conv_5"].output_shape
        net['output'] = ReshapeLayer(net['output_flat'], (-1, img_shape[2], img_shape[3], img_shape[1]))  # (bs, x, y, nrClasses)
        # net['output_for_dice'] = DimshuffleLayer(net['output'], (0, 3, 1, 2))  # (bs, nrClasses, x, y)

        return net


    def create_network(self):

        if self.HP.SEG_INPUT == "Peaks" and self.HP.TYPE == "single_direction":
            # NR_OF_GRADIENTS = 15  # SH-Coeff
            NR_OF_GRADIENTS = 9
        elif self.HP.SEG_INPUT == "Peaks" and self.HP.TYPE == "combined":
            # NR_OF_GRADIENTS = 3
            NR_OF_GRADIENTS = 3*self.HP.NR_OF_CLASSES    # 54
        else:
            NR_OF_GRADIENTS = 33

        if self.HP.RESOLUTION == "1.25mm":
            input_dim = (144, 144)
        elif self.HP.RESOLUTION == "2mm" or self.HP.RESOLUTION == "2.5mm":
            input_dim = (80, 80)


        print("Building network ...")
        print("(Model UNet)")
        # Lasagne Seed for Reproducibility
        L.random.set_rng(np.random.RandomState(1))

        net = self.get_UNet(n_input_channels=NR_OF_GRADIENTS, num_output_classes=self.HP.NR_OF_CLASSES, input_dim=input_dim, base_n_filters=self.HP.UNET_NR_FILT)

        output_layer_for_loss = net["output_flat"]

        if self.HP.LOAD_WEIGHTS:
            print("Loading weights ... ({})".format(join(self.HP.EXP_PATH, self.HP.WEIGHTS_PATH)))
            with np.load(join(self.HP.EXP_PATH, self.HP.WEIGHTS_PATH)) as f: #if both pathes are absolute and beginning of pathes are the same, join will merge the beginning
                param_values = [f['arr_%d' % i] for i in range(len(f.files))]
            L.layers.set_all_param_values(output_layer_for_loss, param_values)


        X_sym = T.tensor4()
        # y_sym = T.imatrix()     # (bs*x*y, nr_of_classes)
        y_sym = T.itensor4()    # (bs, nr_of_classes, x, y)

        prediction_train = L.layers.get_output(output_layer_for_loss, X_sym, deterministic=False)
        prediction_test = L.layers.get_output(output_layer_for_loss, X_sym, deterministic=True)
        output_train = L.layers.get_output(net["output"], X_sym, deterministic=False)
        output_test = L.layers.get_output(net["output"], X_sym, deterministic=True)

        #Calc F1 NEW (simpler)
        output_shuff_train = output_train.dimshuffle((0, 3, 1, 2))  # (bs, nrClasses x, y)
        dice_scores_train = theano_binary_dice_per_instance_and_class(output_shuff_train, y_sym, dim=2, first_spatial_axis=2)  # (bs, nrClasses) -> dice for each class in each batch
        f1_train = T.mean(dice_scores_train)  #average over batches and classes
        dice_scores_train_continuous = theano_binary_dice_per_instance_and_class_for_loss(output_shuff_train, y_sym, dim=2, first_spatial_axis=2)  # (bs, nrClasses) -> dice for each class in each batch
        f1_train_continuous = T.mean(dice_scores_train_continuous)  # average over batches and classes

        output_shuff_test = output_test.dimshuffle((0, 3, 1, 2))  # (bs, nrClasses x, y)
        dice_scores_test = theano_binary_dice_per_instance_and_class(output_shuff_test, y_sym, dim=2, first_spatial_axis=2)  # (bs, nrClasses) -> dice for each class in each batch
        f1_test = T.mean(dice_scores_test)  # average over batches and classes
        dice_scores_test_continuous = theano_binary_dice_per_instance_and_class_for_loss(output_shuff_test, y_sym, dim=2, first_spatial_axis=2)  # (bs, nrClasses) -> dice for each class in each batch
        f1_test_continuous = T.mean(dice_scores_test_continuous)  # average over batches and classes

        loss_train = 1 - f1_train_continuous
        loss_test = 1 - f1_test_continuous

        ##Parameter Updates
        all_params = L.layers.get_all_params(output_layer_for_loss, trainable=True)
        learning_rate = theano.shared(np.float32(self.HP.LEARNING_RATE))
        # updates = L.updates.adam(loss_train, all_params, learning_rate)
        updates = L.updates.adamax(loss_train, all_params, learning_rate)

        # Define Functions
        train_fn = theano.function([X_sym, y_sym], [loss_train, prediction_train, f1_train], updates=updates)  # prediction_TEST, weil hier auch nicht Dropout will bei Score??
        predict_fn = theano.function([X_sym, y_sym], [loss_test, prediction_test, f1_test])

        get_probs = theano.function([X_sym], output_test)

        #Exporting variables
        self.learning_rate = learning_rate
        self.train = train_fn
        self.predict = predict_fn
        self.get_probs = get_probs    # (bs, x, y, nrClasses)
        self.net = net
        self.output = output_layer_for_loss     # this is used for saving weights (could probably also be simplified)
