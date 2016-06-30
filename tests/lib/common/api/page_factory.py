import factory


class PageFactoryOptions(factory.base.FactoryOptions):
    """Configuration for PageFactory
    """
    def _build_default_options(self):
        options = super(PageFactoryOptions, self)._build_default_options()
        options.append(factory.base.OptionDefault(
            'get_or_create', (), inherit=True))
        options.append(factory.base.OptionDefault(
            'resources', (), inherit=True))
        return options


class PageFactory(factory.Factory):
    """Tower API Page Model Base Factory
    """
    _options_class = PageFactoryOptions

    @classmethod
    def _adjust_kwargs(cls, **kwargs):
        resource_keys = [key for key in kwargs if key in cls._meta.resources]
        for key in resource_keys:
            if kwargs[key] is None:
                del kwargs[key]
            else:
                kwargs[key] = kwargs[key].id
        return kwargs

    @classmethod
    def _create(cls, model_class, request, **kwargs):
        """Create data and post to the associated endpoint
        """
        testsetup = request.getfuncargvalue('testsetup')
        model = model_class(testsetup)
        # get or create the requested resource
        if cls._meta.get_or_create:
            obj = cls._get_or_create(model, request, **kwargs)
        else:
            obj = model.post(kwargs)
            request.addfinalizer(obj.silent_delete)
        return obj

    @classmethod
    def _get_or_create(cls, model, request, **kwargs):
        """Create an instance of the model through its associated endpoint
        if it doesn't already exist
        """
        key_fields = {}
        for field in cls._meta.get_or_create:
            if field not in kwargs:
                msg = "{0} initialization value '{1}' not found"
                msg = msg.format(cls.__name__, field)
                raise factory.errors.FactoryError(msg)
            key_fields[field] = kwargs[field]
        try:
            obj = model.get(**key_fields).results.pop()
        except IndexError:
            obj = model.post(kwargs)
            request.addfinalizer(obj.silent_delete)
        return obj

    @classmethod
    def payload(cls, request, **kwargs):
        kwargs['request'] = request
        # generate dependencies
        attrs = cls.attributes(create=True, extra=kwargs)
        attrs = cls._rename_fields(**attrs)
        # extract resource attributes
        resources = {key: attrs.get(key) for key in cls._meta.resources}
        # process resource attributes for payloads
        attrs = cls._adjust_kwargs(**attrs)
        # extract *args
        for key in cls._meta.inline_args:
            del attrs[key]
        # remove any remaining args tagged for exclusion
        for arg in cls._meta.exclude:
            attrs.pop(arg, None)
        # remove any defined parameters
        for arg in cls._meta.parameters:
            attrs.pop(arg, None)
        # remove any resource set to None
        for key, val in resources.items():
            if val is None:
                del resources[key]
        return attrs, resources
