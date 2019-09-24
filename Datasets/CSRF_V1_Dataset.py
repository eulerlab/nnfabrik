import torch
import torch.utils.data as utils
import numpy as np
import pickle
from builtins import property

# datapath = "data/monkeydata/csrf_dataset_one_35ppd.pickle"

def CSRF_V1(datapath, batch_size, seed, image_path=None,
            train_frac=0.8, subsample=1, crop=65, time_bins_sum=tuple(range(7))):


    v1_data = CSRF_V1_Data(raw_data_path=datapath, image_path=image_path, seed=seed,
                        train_frac = train_frac, subsample=subsample, crop=crop,
                        time_bins_sum=time_bins_sum)

    images, responses, valid_responses = v1_data.train()
    train_loader = get_loader_csrf_V1(images, responses, 1 * valid_responses, batch_size)

    images, responses, valid_responses = v1_data.val()
    val_loader = get_loader_csrf_V1(images, responses, 1 * valid_responses, batch_size)

    images, responses, valid_responses = v1_data.test()
    test_loader = get_loader_csrf_V1(images, responses, 1 * valid_responses, batch_size)

    data_loader = dict(train_loader=train_loader,val_loader=val_loader,test_loader=test_loader)
    return data_loader

def get_loader_csrf_V1(images, responses, valid_responses, batch_size):

    # Expected Dimension of the Image Tensor is Images x Channels x size_x x size_y
    # In some CSRF files, Channels are at Dim4, the image tensor is thus reshaped accordingly
    im_shape = images.shape
    if im_shape[1]>1:
        # images = torch.tensor(images).view(im_shape[0], im_shape[3], im_shape[1], im_shape[2]).cuda().to(torch.float)
        images = torch.tensor(images).view(im_shape[0], im_shape[3], im_shape[1], im_shape[2]).to(torch.float)
    else:
        images = torch.tensor(images).cuda().to(torch.float)

    responses = torch.tensor(responses).cuda().to(torch.float)
    valid_responses = torch.tensor(valid_responses).cuda().to(torch.float)
    dataset = utils.TensorDataset(images, responses, valid_responses)
    data_loader = utils.DataLoader(dataset, batch_size=batch_size, shuffle=True)


    return data_loader

class CSRF_V1_Data:
    """For use with George's and Kelli's csrf data set."""

    def __init__(self, raw_data_path, image_path, seed, train_frac, subsample, crop, time_bins_sum):
        """
        Args:
            raw_data_path: Path pointing to the raw data. Defaults to /gpfs01/bethge/share/csrf_data/csrf_dataset_one.pickle
            image_path: if the pickle file does not contain the train_images, load them from another
                file that does contain them
            seed: Seed for train val data set split (does not affect order of stimuli... in train val split themselves)
            train_frac: Fraction of experiments training data used for model training. Remaining data as val set.
            subsample: Integer values to downsample stimuli
            crop: Integer value to crop stimuli from each side (left, right, bottom, top), before subsampling
            time_bins_sum: array-like, values 0[0, ..., 12], time bins to average over. (40ms to 160ms following image onset in steps of 10ms)
        """

        with open(raw_data_path, "rb") as pkl:
            raw_data = pickle.load(pkl)

        # unpack data

        self._subject_ids = raw_data["subject_ids"]
        self._session_ids = raw_data["session_ids"]
        self._session_unit_response_link = raw_data["session_unit_response_link"]
        self._repetitions_test = raw_data["repetitions_test"]
        responses_train = raw_data["responses_train"].astype(np.float32)
        self._responses_test = raw_data["responses_test"].astype(np.float32)

        real_responses = np.logical_not(np.isnan(responses_train))
        self._real_responses_test = np.logical_not(np.isnan(self.responses_test))

        if image_path:
            with open(image_path, "rb") as pkl:
                raw_data = pickle.load(pkl)

        if crop == 0:
            images_train = raw_data["images_train"][:, 0::subsample, 0::subsample]
            images_test = raw_data["images_test"][:, 0::subsample, 0::subsample]
        else:
            images_train = raw_data["images_train"][:, crop:-crop:subsample, crop:-crop:subsample]
            images_test = raw_data["images_test"][:, crop:-crop:subsample, crop:-crop:subsample]

        # z-score all images by mean, and sigma of all images
        all_images = np.append(images_train, images_test, axis=0)
        img_mean = np.mean(all_images)
        img_std = np.std(all_images)
        images_train = (images_train - img_mean) / img_std
        self._images_test = (images_test - img_mean) / img_std

        # split into train and val set, images randomly assigned
        train_split, val_split = self.get_validation_split(real_responses, train_frac, seed)
        self._images_train = images_train[train_split, :, :]
        self._responses_train = responses_train[train_split, :, :]
        self._real_responses_train = real_responses[train_split, :, :]

        self._images_val = images_train[val_split, :, :]
        self._responses_val = responses_train[val_split, :, :]
        self._real_responses_val = real_responses[val_split, :, :]

        self._train_perm = np.random.permutation(self._images_train.shape[0])
        self._val_perm = np.random.permutation(self._images_val.shape[0])

        if time_bins_sum is not None:  # then average over given time bins
            self._responses_train = np.sum(self._responses_train[:, :, time_bins_sum], axis=-1)
            self._responses_test = np.sum(self._responses_test[:, :, time_bins_sum], axis=-1)
            self._responses_val = np.sum(self._responses_val[:, :, time_bins_sum], axis=-1)

            # In real responses: If an entry for any time is False, real_responses is False for all times.
            self._real_responses_train = np.min(self._real_responses_train[:, :, time_bins_sum], axis=-1)
            self._real_responses_test = np.min(self._real_responses_test[:, :, time_bins_sum], axis=-1)
            self._real_responses_val = np.min(self._real_responses_val[:, :, time_bins_sum], axis=-1)

        # in responses, change nan to zero. Then: Use real responses vector for all valid responses
        nan_mask = np.isnan(self._responses_train)
        self._responses_train[nan_mask] = 0.

        nan_mask = np.isnan(self._responses_val)
        self._responses_val[nan_mask] = 0.

        nan_mask = np.isnan(self._responses_test)
        self._responses_test[nan_mask] = 0.

        self._minibatch_idx = 0

    # getters
    @property
    def images_train(self):
        """
        Returns:
            train images in current order (changes every time a new epoch starts)
        """
        return np.expand_dims(self._images_train[self._train_perm], -1)

    @property
    def responses_train(self):
        """
        Returns:
            train responses in current order (changes every time a new epoch starts)
        """
        return self._responses_train[self._train_perm]

    # legacy property
    @property
    def real_resps_train(self):
        return self._real_responses_train[self._train_perm]

    @property
    def real_responses_train(self):
        return self._real_responses_train[self._train_perm]

    @property
    def images_val(self):
        return np.expand_dims(self._images_val, -1)

    @property
    def responses_val(self):
        return self._responses_val

    @property
    def images_test(self):
        return np.expand_dims(self._images_test, -1)

    @property
    def responses_test(self):
        return self._responses_test

    @property
    def image_dimensions(self):
        return self.images_train.shape[1:3]

    @property
    def num_neurons(self):
        return self.responses_train.shape[1]

    # methods
    def next_epoch(self):
        """
        Gets new random index permutation for train set, reset minibatch index.
        """
        self._minibatch_idx = 0
        self._train_perm = np.random.permutation(self._train_perm)

    def get_validation_split(self, real_responses_train, train_frac=0.8, seed=None):
        """
            Splits the Training Data into the trainset and validation set.
            The Validation set should recruit itself from the images that most neurons have seen.

        :return: returns permuted indeces for the training and validation set
        """
        if seed:
            np.random.seed(seed)  # only affects the next call of a random number generator, i.e. np.random.permutation

        num_images = real_responses_train.shape[0]
        Neurons_per_image = np.sum(real_responses_train, axis=1)[:, 0]
        Neurons_per_image_sort_idx = np.argsort(Neurons_per_image)

        top_images = Neurons_per_image_sort_idx[-int(np.floor(train_frac / 2 * num_images)):]
        val_images_idx = np.random.choice(top_images, int(len(top_images) / 2), replace=False)

        train_idx_filter = np.logical_not(np.isin(Neurons_per_image_sort_idx, val_images_idx))
        train_images_idx = np.random.permutation(Neurons_per_image_sort_idx[train_idx_filter])

        return train_images_idx, val_images_idx

    # Methods for compatibility with Santiago's code base.
    def train(self):
        """
            For compatibility with Santiago's code base.

            Returns:
                images_train, responses_train, real_respsonses_train
            """

        return self.images_train, self.responses_train, self.real_responses_train

    def val(self):
        """
        For compatibility with Santiago's code base.

        Returns:
            images_val, responses_val, real_respsonses_val
        """

        return self.images_val, self.responses_val, self._real_responses_val

    def test(self):
        """
            For compatibility with Santiago's code base.

            Returns:
                images_test, responses_test, real_responses_test
            """

        return self.images_test, self.responses_test, self._real_responses_test