import cvxpy as cp
import numpy as np

from PEPit.point import Point
from PEPit.expression import Expression
from PEPit.constraint import Constraint
from PEPit.psd_matrix import PSDMatrix


class Cvxpy_wrapper(object):
    def __init__(self):
        """

    Attributes:
    
                            
        """
        # Initialize lists of constraints that are used to solve the SDP.
        # Those lists should not be updated by hand, only the solve method does update them.
        self._list_of_constraints_sent_to_solver = list()
        self._list_of_solver_constraints = list()
        self.F = cp.Variable((Expression.counter+1,)) # need the +1 because the objective will be created afterwards
        self.G = cp.Variable((Point.counter, Point.counter), symmetric=True)

        # Express the constraints from F, G and objective
        # Start with the main LMI condition
        self._list_of_solver_constraints = [self.G >> 0]
        
    def _expression_to_solver(self, expression):
        """
        Create a cvxpy compatible expression from an :class:`Expression`.

        Args:
            expression (Expression): any expression.
            F (cvxpy Variable): a vector representing the function values.
            G (cvxpy Variable): a matrix representing the Gram matrix of all leaf :class:`Point` objects.

        Returns:
            cvxpy_variable (cvxpy Variable): The expression in terms of F and G.

        """
        cvxpy_variable = 0
        Fweights = np.zeros((Expression.counter,))
        Gweights = np.zeros((Point.counter, Point.counter))

        # If simple function value, then simply return the right coordinate in F
        if expression.get_is_leaf():
            Fweights[expression.counter] += 1
        # If composite, combine all the cvxpy expression found from leaf expressions
        else:
            for key, weight in expression.decomposition_dict.items():
                # Function values are stored in F
                if type(key) == Expression:
                    assert key.get_is_leaf()
                    Fweights[key.counter] = weight
                # Inner products are stored in G
                elif type(key) == tuple:
                    point1, point2 = key
                    assert point1.get_is_leaf()
                    assert point2.get_is_leaf()
                    Gweights[point1.counter, point2.counter] = weight
                # Constants are simply constants
                elif key == 1:
                    cvxpy_variable = weight
                # Others don't exist and raise an Exception
                else:
                    raise TypeError("Expressions are made of function values, inner products and constants only!")

        Gweights = (Gweights + Gweights.T)/2
        cvxpy_variable += self.F @ Fweights + cp.sum(cp.multiply(self.G, Gweights))

        # Return the input expression in a cvxpy variable
        return cvxpy_variable
    
    def send_constraint_to_solver(self, constraint):
        """
        Transform a PEPit :class:`Constraint` into a CVXPY one
        and add the 2 formats of the constraints into the tracking lists.

        Args:
            constraint (Constraint): a :class:`Constraint` object to be sent to CVXPY.
            F (CVXPY Variable): a CVXPY Variable referring to function values.
            G (CVXPY Variable): a CVXPY Variable referring to points and gradients.

        Raises:
            ValueError if the attribute `equality_or_inequality` of the :class:`Constraint`
            is neither `equality`, nor `inequality`.

        """

        # Sanity check
        assert isinstance(constraint, Constraint)

        # Add constraint to the attribute _list_of_constraints_sent_to_solver to keep track of
        # all the constraints that have been sent to CVXPY as well as the order.
        self._list_of_constraints_sent_to_solver.append(constraint)

        # Distinguish equality and inequality
        if constraint.equality_or_inequality == 'inequality':
            cvxpy_constraint = self._expression_to_solver(constraint.expression) <= 0
        elif constraint.equality_or_inequality == 'equality':
            cvxpy_constraint = self._expression_to_solver(constraint.expression) == 0
        else:
            # Raise an exception otherwise
            raise ValueError('The attribute \'equality_or_inequality\' of a constraint object'
                             ' must either be \'equality\' or \'inequality\'.'
                             'Got {}'.format(constraint.equality_or_inequality))

        # Add the corresponding CVXPY constraint to the list of constraints to be sent to CVXPY
        self._list_of_solver_constraints.append(cvxpy_constraint)

    def send_lmi_constraint_to_solver(self, psd_counter, psd_matrix, verbose):
        """
        Transform a PEPit :class:`PSDMatrix` into a CVXPY symmetric PSD matrix
        and add the 2 formats of the constraints into the tracking lists.

        Args:
            psd_counter (int): a counter useful for the verbose mode.
            psd_matrix (PSDMatrix): a matrix of expressions that is constrained to be PSD.
            F (CVXPY Variable): a CVXPY Variable referring to function values.
            G (CVXPY Variable): a CVXPY Variable referring to points and gradients.
            verbose (int): Level of information details to print (Override the CVXPY solver verbose parameter).

                            - 0: No verbose at all
                            - 1: PEPit information is printed but not CVXPY's
                            - 2: Both PEPit and CVXPY details are printed

        """

        # Sanity check
        assert isinstance(psd_matrix, PSDMatrix)

        # Add psd_matrix to the attribute _list_of_constraints_sent_to_solver to keep track of
        # all the constraints that have been sent to CVXPY as well as the order.
        self._list_of_constraints_sent_to_solver.append(psd_matrix)

        # Create a symmetric matrix in CVXPY
        M = cp.Variable(psd_matrix.shape, symmetric=True)

        # Store the lmi constraint
        cvxpy_constraints_list = [M >> 0]

        # Store one correspondence constraint per entry of the matrix
        for i in range(psd_matrix.shape[0]):
            for j in range(psd_matrix.shape[1]):
                cvxpy_constraints_list.append(M[i, j] == self._expression_to_solver(psd_matrix[i, j]))

        # Print a message if verbose mode activated
        if verbose:
            print('\t\t Size of PSD matrix {}: {}x{}'.format(psd_counter + 1, *psd_matrix.shape))

        # Add the corresponding CVXPY constraints to the list of constraints to be sent to CVXPY
        self._list_of_solver_constraints += cvxpy_constraints_list

    def generate_problem(self, objective):
        self.objective = objective
        self.prob = cp.Problem(objective=cp.Maximize(objective), constraints=self._list_of_solver_constraints)
        return self.prob
        
    def get_dual_variables(self):
        assert self._list_of_solver_constraints == self.prob.constraints
        dual_values = [constraint.dual_value for constraint in self.prob.constraints]
        return dual_values
        
    def prepare_heuristic(self, wc_value, tol_dimension_reduction):
        # Add the constraint that the objective stay close to its actual value
        self._list_of_solver_constraints.append(self.objective >= wc_value - tol_dimension_reduction)
        
    def heuristic(self, weight=1):
        obj = cp.trace(cp.multiply(self.G, weight))
        prob = cp.Problem(objective=cp.Minimize(obj), constraints=self._list_of_solver_constraints)
        return prob
